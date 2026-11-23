"""Directory listing filters (Ctrl+I), the filter rules editor, and Search remote files (F3), as FileZilla's."""

from __future__ import annotations

import copy
import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTreeView, QVBoxLayout,
                               QWidget)

from . import filters, remote
from .filters import Condition, Filter
from .widgets import Header


def _shell(dlg: QDialog, header: str) -> QVBoxLayout:
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 16)
    root.addWidget(Header(header))
    body = QVBoxLayout()
    body.setContentsMargins(20, 12, 20, 0)
    root.addLayout(body, 1)
    return body


def _ok_cancel(dlg) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


class ConditionsEditor(QWidget):
    """Rows of [field] [test] [value] [-], and [+] to add one: a filter's or a search's conditions."""

    def __init__(self, parent=None, remote_side: bool = True):
        super().__init__(parent)
        self.remote_side = remote_side
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.rows: list[tuple] = []
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(40)
        self.add_button.setToolTip("Add a condition")
        self.add_button.clicked.connect(lambda: self.add(Condition()))

    def set_conditions(self, conds: list[Condition]):
        for w in list(self.rows):
            self._remove(w)
        for c in conds or [Condition()]:
            self.add(c)

    def add(self, c: Condition):
        fieldbox = QComboBox()
        for k, text in filters.FIELDS.items():
            if k == "perms" and not self.remote_side:
                continue
            fieldbox.addItem(text, k)
        opbox = QComboBox()
        value = QLineEdit(c.value)
        minus = QPushButton("−")
        minus.setFixedWidth(40)
        minus.setToolTip("Remove this condition")
        row = (fieldbox, opbox, value, minus)

        def fill_ops(_=None, keep=None):
            ops = filters.ops_for(fieldbox.currentData())
            opbox.clear()
            for k, text in ops.items():
                opbox.addItem(text, k)
            if keep in ops:
                opbox.setCurrentIndex(list(ops).index(keep))
            hint = {"size": "bytes, or 1.5 MB, 200 KB", "date": "YYYY-MM-DD"}.get(fieldbox.currentData(), "")
            value.setPlaceholderText(hint)
        keys = [fieldbox.itemData(i) for i in range(fieldbox.count())]
        fieldbox.setCurrentIndex(keys.index(c.field) if c.field in keys else 0)
        fill_ops(keep=c.op)
        fieldbox.currentIndexChanged.connect(fill_ops)
        minus.clicked.connect(lambda: self._remove(row) if len(self.rows) > 1 else None)
        self.rows.append(row)
        self._layout()

    def _remove(self, row):
        self.rows.remove(row)
        for w in row:
            w.setParent(None)
            w.deleteLater()
        self._layout()

    def _layout(self):
        for i, row in enumerate(self.rows):
            for c, w in enumerate(row):
                self.grid.addWidget(w, i, c)
        self.grid.addWidget(self.add_button, len(self.rows), 3)
        self.grid.setColumnStretch(2, 1)

    def conditions(self) -> list[Condition]:
        return [Condition(f.currentData(), o.currentData(), v.text()) for f, o, v, _ in self.rows]


class FilterEditor(QDialog):
    """Edit filter rules: every filter's conditions, what they apply to, how they combine."""

    def __init__(self, fs: filters.FilterSet, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit filter rules")
        self.resize(1000, 560)
        self.filters = [copy.deepcopy(f) for f in fs.filters]
        self.renamed: dict[str, str] = {}
        body = _shell(self, "FILTER RULES")
        main = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(_field("Filters"))
        self.list = QListWidget()
        self.list.addItems([f.name for f in self.filters])
        self.list.currentRowChanged.connect(self._picked)
        left.addWidget(self.list, 1)
        g = QGridLayout()
        for i, (text, fn) in enumerate((("New", self.new), ("Copy", self.copy), ("Rename", self.rename),
                                        ("Delete", self.delete))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        left.addLayout(g)
        main.addLayout(left, 2)
        right = QVBoxLayout()
        self.match = QComboBox()
        for k, text in filters.MATCH.items():
            self.match.addItem(text, k)
        right.addWidget(self.match)
        self.conds = ConditionsEditor(self)
        right.addWidget(self.conds)
        opts = QHBoxLayout()
        self.files = QCheckBox("Filter files")
        self.dirs = QCheckBox("Filter directories")
        self.case = QCheckBox("Case-sensitive")
        for c in (self.files, self.dirs, self.case):
            opts.addWidget(c)
        opts.addStretch(1)
        right.addLayout(opts)
        right.addStretch(1)
        main.addLayout(right, 4)
        body.addLayout(main, 1)
        body.addWidget(_ok_cancel(self))
        self.current = -1
        if self.filters:
            self.list.setCurrentRow(0)

    def _store(self):
        if 0 <= self.current < len(self.filters):
            f = self.filters[self.current]
            f.match = self.match.currentData()
            f.conditions = self.conds.conditions()
            f.files, f.dirs, f.case = self.files.isChecked(), self.dirs.isChecked(), self.case.isChecked()

    def _picked(self, row):
        self._store()
        self.current = row
        if 0 <= row < len(self.filters):
            f = self.filters[row]
            self.match.setCurrentIndex(list(filters.MATCH).index(f.match) if f.match in filters.MATCH else 0)
            self.conds.set_conditions(f.conditions)
            self.files.setChecked(f.files)
            self.dirs.setChecked(f.dirs)
            self.case.setChecked(f.case)

    def _unique(self, name):
        names = {f.name for f in self.filters}
        n, out = 2, name
        while out in names:
            out = f"{name} ({n})"
            n += 1
        return out

    def new(self, name: str | None = None):
        self._store()
        self.filters.append(Filter(self._unique(name or "New filter"), [Condition()]))
        self.list.addItem(self.filters[-1].name)
        self.list.setCurrentRow(len(self.filters) - 1)

    def copy(self):
        if 0 <= self.current < len(self.filters):
            self._store()
            f = copy.deepcopy(self.filters[self.current])
            f.name = self._unique(f.name + " (copy)")
            self.filters.append(f)
            self.list.addItem(f.name)
            self.list.setCurrentRow(len(self.filters) - 1)

    def rename(self, name: str | None = None):
        if not 0 <= self.current < len(self.filters):
            return
        old = self.filters[self.current].name
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename filter", "New name:", text=old)
            if not ok:
                return
        name = name.strip()
        if name and name != old:
            name = self._unique(name)
            self.filters[self.current].name = name
            self.list.item(self.current).setText(name)
            self.renamed[old] = name

    def delete(self):
        if 0 <= self.current < len(self.filters):
            row = self.current
            del self.filters[row]
            self.current = -1
            self.list.takeItem(row)
            if self.filters:
                self.list.setCurrentRow(min(row, len(self.filters) - 1))

    def result_filters(self) -> list[Filter]:
        self._store()
        return self.filters


class FiltersDialog(QDialog):
    """Directory listing filters: each filter switched on for the local and/or the remote side."""

    def __init__(self, fs: filters.FilterSet, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Directory listing filters")
        self.resize(720, 520)
        self.fs = filters.FilterSet(copy.deepcopy(fs.filters), set(fs.local), set(fs.remote))
        body = _shell(self, "FILTERS")
        hint = QLabel("A ticked filter hides what it matches, in the lists and in folder transfers.")
        hint.setProperty("role", "dim")
        body.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["FILTER", "LOCAL", "REMOTE"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        body.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Edit filter rules...", self.edit), ("Enable all", lambda: self._all(True)),
                         ("Disable all", lambda: self._all(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        body.addLayout(row)
        body.addWidget(_ok_cancel(self))
        self._fill()

    def _fill(self):
        self.table.setRowCount(len(self.fs.filters))
        self.boxes = []
        for r, f in enumerate(self.fs.filters):
            it = QTableWidgetItem(f.name)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            pair = []
            for c, side in ((1, self.fs.local), (2, self.fs.remote)):
                cb = QCheckBox()
                cb.setChecked(f.name in side)
                w = QWidget()
                lay = QHBoxLayout(w)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addWidget(cb, 0, Qt.AlignCenter)
                self.table.setCellWidget(r, c, w)
                pair.append(cb)
            self.boxes.append(pair)

    def _sync(self):
        self.fs.local = {f.name for f, (l, _) in zip(self.fs.filters, self.boxes) if l.isChecked()}
        self.fs.remote = {f.name for f, (_, r) in zip(self.fs.filters, self.boxes) if r.isChecked()}

    def set_on(self, name: str, local: bool | None = None, remote_on: bool | None = None):
        for f, (l, r) in zip(self.fs.filters, self.boxes):
            if f.name == name:
                if local is not None:
                    l.setChecked(local)
                if remote_on is not None:
                    r.setChecked(remote_on)

    def _all(self, on: bool):
        for l, r in self.boxes:
            l.setChecked(on)
            r.setChecked(on)

    def edit(self):
        self._sync()
        dlg = FilterEditor(self.fs, self)
        self._editor = dlg
        if dlg.exec():
            self.apply_edit(dlg)

    def apply_edit(self, dlg: FilterEditor):
        new = dlg.result_filters()
        names = {f.name for f in new}
        for side in (self.fs.local, self.fs.remote):
            for old, nw in dlg.renamed.items():
                if old in side:
                    side.discard(old)
                    side.add(nw)
            side &= names
        self.fs.filters = new
        self._fill()

    def result(self) -> filters.FilterSet:
        self._sync()
        return self.fs


# ------------------------------------------------------------------------------------------ search
class ResultModel(QAbstractTableModel):
    COLUMNS = ["Filename", "Path", "Filesize", "Filetype", "Last modified"]

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, remote.Entry]] = []

    def add(self, path, entry):
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append((path, entry))
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.rows = []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.COLUMNS[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        path, e = self.rows[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            return [e.name, remote.parent(path), "" if e.is_dir else f"{e.size:,}",
                    "Directory" if e.is_dir else (e.name.rsplit(".", 1)[-1].upper() + " File" if "." in e.name
                                                  else "File"), remote.fmt_time(e.mtime)][c]
        if role == Qt.TextAlignmentRole and c == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class SearchDialog(QDialog):
    """Search remote files: conditions, Search / Stop, the results; Download, Delete, Go to folder."""

    _found = Signal(str, object)
    _progress = Signal(str)
    _finished = Signal(int)

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle("Search remote files")
        self.resize(1100, 720)
        body = _shell(self, "SEARCH REMOTE FILES")
        g = QGridLayout()
        g.addWidget(_field("Search directory"), 0, 0)
        self.start = QLineEdit(window.remote.path or "/")
        g.addWidget(self.start, 0, 1)
        self.match = QComboBox()
        self.match.addItem("Match all of the following", "all")
        self.match.addItem("Match any of the following", "any")
        g.addWidget(self.match, 1, 0, 1, 2)
        g.setColumnStretch(1, 1)
        body.addLayout(g)
        self.conds = ConditionsEditor(self)
        self.conds.set_conditions([Condition("name", "contains", "")])
        body.addWidget(self.conds)
        opts = QHBoxLayout()
        self.files = QCheckBox("Find files")
        self.files.setChecked(True)
        self.dirs = QCheckBox("Find directories")
        self.dirs.setChecked(True)
        self.case = QCheckBox("Case-sensitive")
        for c in (self.files, self.dirs, self.case):
            opts.addWidget(c)
        opts.addStretch(1)
        self.go = QPushButton("Search")
        self.go.setDefault(True)
        self.go.clicked.connect(self.toggle)
        opts.addWidget(self.go)
        body.addLayout(opts)
        self.model = ResultModel()
        self.view = QTreeView()
        self.view.setRootIsDecorated(False)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setModel(self.model)
        for i, w in enumerate([260, 380, 110, 110]):
            self.view.header().resizeSection(i, w)
        self.view.header().setStretchLastSection(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(lambda i: self.go_to(self.model.rows[i.row()][0]))
        body.addWidget(self.view, 1)
        self.status = QLabel("")
        self.status.setProperty("role", "dim")
        body.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        body.addWidget(close)
        self._found.connect(self.model.add)
        self._progress.connect(lambda f: self.status.setText(f"Searching {f} ... {len(self.model.rows)} found"))
        self._finished.connect(self._done)
        self.thread = None
        self.stop_flag = False

    def criteria(self) -> Filter:
        return Filter("search", self.conds.conditions(), self.match.currentData(), self.files.isChecked(),
                      self.dirs.isChecked(), self.case.isChecked())

    def toggle(self):
        if self.thread is not None and self.thread.is_alive():
            self.stop_flag = True
            return
        if not self.window.browser.connected:
            QMessageBox.information(self, "Search", "Connect to a server first.")
            return
        self.model.clear()
        self.stop_flag = False
        self.go.setText("Stop")
        site, start, crit = self.window.site, self.start.text().strip() or "/", self.criteria()
        browser = self.window.browser

        def run():
            from .search import search
            n = 0
            try:
                sess = browser.open(site)  # its own connection: browsing and transfers carry on
                try:
                    n = search(sess, start, crit, lambda p, e: self._found.emit(p, e), self._progress.emit,
                               lambda: self.stop_flag, browser.log)
                finally:
                    sess.close()
            except remote.RemoteError as e:
                browser.logged.emit("Error", f"Search: {e}")
            self._finished.emit(n)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def _done(self, folders):
        self.go.setText("Search")
        stopped = " (stopped)" if self.stop_flag else ""
        self.status.setText(f"{len(self.model.rows)} found in {folders} folder(s){stopped}.")

    def wait(self, timeout=30):
        """Tests: until the search has finished."""
        import time
        from PySide6.QtWidgets import QApplication
        end = time.monotonic() + timeout
        while self.thread is not None and self.thread.is_alive() and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)
        QApplication.processEvents()

    def selected(self):
        return [self.model.rows[i.row()] for i in self.view.selectionModel().selectedRows()]

    def _menu(self, pos):
        sel = self.selected()
        m = QMenu(self)
        m.addAction("Download", lambda: self.download(sel)).setEnabled(bool(sel))
        m.addAction("Go to folder", lambda: self.go_to(sel[0][0])).setEnabled(len(sel) == 1)
        m.addSeparator()
        m.addAction("Delete", lambda: self.delete(sel)).setEnabled(bool(sel))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def download(self, sel):
        """Into the local site's folder, keeping each one's name (as FileZilla's search does)."""
        import os
        q = self.window._queue()
        if q is None:
            return
        for path, e in sel:
            q.download(path, os.path.join(self.window.local.path, e.name), e)
        q.start()

    def delete(self, sel, confirm=True):
        if confirm and QMessageBox.question(self, "Search", f"Really delete {len(sel)} item(s) from the server?",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        targets = [(p, e.is_dir and not e.is_link) for p, e in sel]

        def rm_all(sess):
            def rm(path, is_dir):
                if is_dir:
                    for e in sess.list(path):
                        rm(remote.join(path, e.name), e.is_dir and not e.is_link)
                    sess.rmdir(path)
                else:
                    sess.delete(path)
            for p, d in targets:
                rm(p, d)

        def done(_):
            gone = {p for p, _ in targets}
            keep = [(p, e) for p, e in self.model.rows if p not in gone and not any(
                p.startswith(g.rstrip("/") + "/") for g in gone)]
            self.model.beginResetModel()
            self.model.rows = keep
            self.model.endResetModel()
            self.window.navigate(self.window.remote.path)
        self.window.browser.run(rm_all, done, lambda e: self.window.log("Error", e))

    def go_to(self, path):
        self.window.navigate(remote.parent(path))
