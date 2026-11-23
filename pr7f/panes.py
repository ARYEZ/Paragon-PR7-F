"""The local and remote sites: path box, folder tree, file list and its summary line, as FileZilla's panes.

Lists are plain Python list models (never QStandardItemModel: PR7-Z's crash). Dragging files from one list to the
other asks the window to transfer them (`transfer_requested`); Explorer's files dropped on the remote list upload.
"""

from __future__ import annotations

import os
import posixpath
import string

from PySide6.QtCore import QAbstractTableModel, QDir, QMimeData, QModelIndex, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileSystemModel, QHBoxLayout, QHeaderView, QLabel,
                               QSplitter, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import remote, theme
from .widgets import file_icon

LOCAL_MIME = "application/x-pr7f-local"
REMOTE_MIME = "application/x-pr7f-remote"


def _size(n: int) -> str:
    return f"{n:,}"


def _type(name: str, is_dir: bool, remote_side: bool) -> str:
    if is_dir:
        return "Directory" if remote_side else "File folder"
    ext = os.path.splitext(name)[1][1:]
    return f"{ext.upper()} File" if ext else "File"


class Row:
    __slots__ = ("name", "size", "mtime", "is_dir", "perms", "owner", "is_link", "kind")

    def __init__(self, name, size=0, mtime=0.0, is_dir=False, perms="", owner="", is_link=False, kind=""):
        self.name, self.size, self.mtime, self.is_dir = name, size, mtime, is_dir
        self.perms, self.owner, self.is_link = perms, owner, is_link
        self.kind = kind or ("folder" if is_dir else "file")


class ListModel(QAbstractTableModel):
    def __init__(self, columns: list[str], remote_side: bool):
        super().__init__()
        self.columns, self.remote_side = columns, remote_side
        self.rows: list[Row] = []
        self.marks: dict[str, str] = {}  # directory comparison: name -> "differs" | "only"
        self.icons = {k: file_icon(k) for k in ("up", "folder", "file", "drive")}
        self.sort_col, self.sort_desc = 0, False

    def set_rows(self, rows: list[Row]):
        self.beginResetModel()
        self.rows = rows
        self._sort()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.columns[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = self.columns[index.column()]
        if role == Qt.DisplayRole:
            if c == "Filename":
                return r.name
            if c == "Filesize":
                return "" if r.is_dir or r.kind in ("up", "drive") else _size(r.size)
            if c == "Filetype":
                return "" if r.kind in ("up", "drive") else _type(r.name, r.is_dir, self.remote_side)
            if c == "Last modified":
                return remote.fmt_time(r.mtime)
            if c == "Permissions":
                return r.perms
            if c == "Owner/Group":
                return r.owner
        if role == Qt.DecorationRole and index.column() == 0:
            return self.icons.get(r.kind)
        if role == Qt.TextAlignmentRole and c == "Filesize":
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and r.name in self.marks:
            from PySide6.QtGui import QColor
            return QColor(theme.LED_ORANGE if self.marks[r.name] == "differs" else theme.ACCENT)
        if role == Qt.ToolTipRole and r.name in self.marks:
            return {"differs": "Different size or date on the other side", "only": "Not on the other side"}[
                self.marks[r.name]]
        return None

    def _sort(self):
        key = {0: lambda r: r.name.lower(), 1: lambda r: r.size, 2: lambda r: _type(r.name, r.is_dir, False),
               3: lambda r: r.mtime}.get(self.sort_col, lambda r: r.name.lower())
        up = [r for r in self.rows if r.kind in ("up",)]
        rest = [r for r in self.rows if r.kind not in ("up",)]
        dirs = sorted([r for r in rest if r.is_dir], key=key, reverse=self.sort_desc)
        files = sorted([r for r in rest if not r.is_dir], key=key, reverse=self.sort_desc)
        self.rows = up + dirs + files  # folders first, as FileZilla

    def sort(self, column, order=Qt.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        self.sort_col, self.sort_desc = column, order == Qt.DescendingOrder
        self._sort()
        self.layoutChanged.emit()

    def supportedDragActions(self):
        return Qt.CopyAction

    def flags(self, index):
        f = super().flags(index)
        if index.isValid() and self.rows[index.row()].kind not in ("up", "drive"):
            f |= Qt.ItemIsDragEnabled
        return f


class FileList(QTreeView):
    """A file list with the family selection band; drags carry the names, drops ask for a transfer."""

    dropped = Signal(str, list, str)  # (source "local"/"remote"/"explorer", paths or names, target subfolder or "")

    def __init__(self, model: ListModel, widths, side: str):
        super().__init__()
        self.side = side
        self.setModel(model)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(18, 18))
        self.setSortingEnabled(True)
        self.header().setSortIndicator(0, Qt.AscendingOrder)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        for i, w in enumerate(widths):
            self.header().resizeSection(i, w)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(QHeaderView.Interactive)
        self.paths = None  # set by the pane: row -> full path

    def drawRow(self, painter: QPainter, option, index):
        super().drawRow(painter, option, index)
        if self.selectionModel().isRowSelected(index.row(), index.parent()):
            r = QRectF(option.rect)
            r.setLeft(0)
            r.setRight(self.viewport().width())
            painter.save()
            painter.fillRect(r, theme.family_gradient(r.left(), 0, r.right(), 0, theme.LIT, 0.22))
            painter.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 1))
            painter.drawLine(QPointF(r.left(), r.top() + 0.5), QPointF(r.right(), r.top() + 0.5))
            painter.drawLine(QPointF(r.left(), r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
            painter.restore()

    def startDrag(self, actions):
        from PySide6.QtGui import QDrag
        names = [self.model().rows[i.row()].name for i in self.selectionModel().selectedRows()
                 if self.model().rows[i.row()].kind not in ("up", "drive")]
        if not names:
            return
        md = QMimeData()
        md.setData(LOCAL_MIME if self.side == "local" else REMOTE_MIME, "\n".join(names).encode("utf-8"))
        if self.side == "local" and self.paths:
            md.setUrls([QUrl.fromLocalFile(self.paths(n)) for n in names])
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.CopyAction)

    def _source(self, md):
        if md.hasFormat(REMOTE_MIME) and self.side == "local":
            return "remote", bytes(md.data(REMOTE_MIME)).decode("utf-8").split("\n")
        if md.hasFormat(LOCAL_MIME) and self.side == "remote":
            return "local", bytes(md.data(LOCAL_MIME)).decode("utf-8").split("\n")
        if md.hasUrls() and self.side == "remote" and not md.hasFormat(LOCAL_MIME):
            return "explorer", [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        return None, []

    def dragEnterEvent(self, e):
        if self._source(e.mimeData())[0]:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._source(e.mimeData())[0]:
            e.acceptProposedAction()

    def dropEvent(self, e):
        src, items = self._source(e.mimeData())
        if not src:
            return
        e.acceptProposedAction()
        idx = self.indexAt(e.position().toPoint())
        target = ""
        if idx.isValid():
            r = self.model().rows[idx.row()]
            if r.is_dir and r.kind == "folder":
                target = r.name  # dropped on a folder: into it
        self.dropped.emit(src, items, target)


def _site_header(title: str) -> tuple[QHBoxLayout, QComboBox]:
    row = QHBoxLayout()
    lab = QLabel(title.upper())
    lab.setProperty("role", "field")
    row.addWidget(lab)
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.NoInsert)
    row.addWidget(box, 1)
    return row, box


def _tree_style(t):
    t.setStyleSheet(f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; color: #FFFFFF; }}"
                    " QTreeView::branch:selected { background: transparent; }")


def summary(rows: list[Row], selected: list[Row]) -> str:
    if selected:
        files = [r for r in selected if not r.is_dir]
        dirs = [r for r in selected if r.is_dir]
        return f"Selected {len(files)} file(s) and {len(dirs)} director{'y' if len(dirs) == 1 else 'ies'}. " \
               f"Total size: {_size(sum(r.size for r in files))} bytes"
    real = [r for r in rows if r.kind not in ("up", "drive")]
    files = [r for r in real if not r.is_dir]
    dirs = [r for r in real if r.is_dir]
    if not real:
        return "Empty directory."
    return f"{len(files)} file{'' if len(files) == 1 else 's'} and {len(dirs)} director" \
           f"{'y' if len(dirs) == 1 else 'ies'}. Total size: {_size(sum(r.size for r in files))} bytes"


class LocalPane(QWidget):
    """Local site. Windows: an empty path is "This PC" (the drives)."""

    navigated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        row, self.box = _site_header("Local site")
        self.box.lineEdit().returnPressed.connect(lambda: self.go(self.box.currentText()))
        col.addLayout(row)
        self.split = QSplitter(Qt.Vertical)
        self.fsmodel = QFileSystemModel()
        self.fsmodel.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.fsmodel.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fsmodel)
        for i in (1, 2, 3):
            self.tree.hideColumn(i)
        self.tree.setHeaderHidden(True)
        _tree_style(self.tree)
        self.tree.clicked.connect(lambda i: self.go(self.fsmodel.filePath(i)))
        self.fsmodel.directoryLoaded.connect(self._tree_loaded)  # the tree fills in the background
        self.split.addWidget(self.tree)
        self.model = ListModel(["Filename", "Filesize", "Filetype", "Last modified"], False)
        self.list = FileList(self.model, [300, 110, 120], "local")
        self.list.paths = lambda name: os.path.join(self.path, name)
        self.list.doubleClicked.connect(self._double)
        self.list.selectionModel().selectionChanged.connect(lambda *_: self._summary())
        self.split.addWidget(self.list)
        self.split.setSizes([160, 400])
        col.addWidget(self.split, 1)
        self.info = QLabel("")
        self.info.setProperty("role", "dim")
        col.addWidget(self.info)
        self.on_open_file = None  # double-click on a file: the window uploads it

    def go(self, path: str) -> bool:
        path = (path or "").strip()
        if path and not os.path.isdir(path):
            self.info.setText(f"{path}: no such folder")
            return False
        rows: list[Row] = []
        if not path and os.name == "nt":
            for letter in string.ascii_uppercase:
                if os.path.exists(f"{letter}:\\"):
                    rows.append(Row(f"{letter}:", kind="drive", is_dir=True))
        else:
            path = os.path.abspath(path or os.path.expanduser("~"))
            if os.path.dirname(path) != path or os.name == "nt":
                rows.append(Row("..", is_dir=True, kind="up"))
            try:
                with os.scandir(path) as it:
                    for e in it:
                        try:
                            st = e.stat()
                            d = e.is_dir()
                        except OSError:
                            continue
                        rows.append(Row(e.name, 0 if d else st.st_size, st.st_mtime, d))
            except OSError as ex:
                self.info.setText(f"{path}: {ex.strerror}")
                return False
        self.path = path
        self.model.set_rows(rows)
        shown = path + (os.sep if path and not path.endswith(os.sep) else "")
        self.box.setEditText(shown)
        if path:
            self.tree.setCurrentIndex(self.fsmodel.index(path))
            self.tree.scrollTo(self.fsmodel.index(path))
        self._summary()
        self.navigated.emit(path)
        return True

    def _tree_loaded(self, folder: str):
        if self.path and os.path.normcase(self.path).startswith(os.path.normcase(folder)):
            idx = self.fsmodel.index(self.path)
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx)

    def refresh(self):
        self.go(self.path)

    def up(self):
        if not self.path:
            return
        parent = os.path.dirname(self.path.rstrip("\\/"))
        if os.name == "nt" and (parent == self.path.rstrip("\\/") or len(self.path.rstrip("\\/")) <= 2):
            self.go("")  # above a drive: This PC
        else:
            self.go(parent or self.path)

    def _double(self, index):
        r = self.model.rows[index.row()]
        if r.kind == "up":
            self.up()
        elif r.kind == "drive":
            self.go(r.name + "\\")
        elif r.is_dir:
            self.go(os.path.join(self.path, r.name))
        elif self.on_open_file:
            self.on_open_file([r])

    def selected(self) -> list[Row]:
        return [self.model.rows[i.row()] for i in self.list.selectionModel().selectedRows()
                if self.model.rows[i.row()].kind not in ("up", "drive")]

    def full(self, name: str) -> str:
        return os.path.join(self.path, name)

    def _summary(self):
        self.info.setText(summary(self.model.rows, self.selected()))


class RemotePane(QWidget):
    """Remote site: filled from the browsing connection; the tree remembers the folders visited."""

    navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        self.entries: list[remote.Entry] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        row, self.box = _site_header("Remote site")
        self.box.lineEdit().returnPressed.connect(lambda: self.navigate_requested.emit(self.box.currentText().strip()))
        col.addLayout(row)
        self.split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(18, 18))
        _tree_style(self.tree)
        self.tree.itemClicked.connect(lambda it, _c: self.navigate_requested.emit(it.data(0, Qt.UserRole)))
        self.nodes: dict[str, QTreeWidgetItem] = {}
        self.split.addWidget(self.tree)
        self.model = ListModel(["Filename", "Filesize", "Filetype", "Last modified", "Permissions", "Owner/Group"],
                               True)
        self.list = FileList(self.model, [270, 110, 100, 150, 110], "remote")
        self.list.doubleClicked.connect(self._double)
        self.list.selectionModel().selectionChanged.connect(lambda *_: self._summary())
        self.split.addWidget(self.list)
        self.split.setSizes([160, 400])
        col.addWidget(self.split, 1)
        self.info = QLabel("Not connected to any server")
        self.info.setProperty("role", "dim")
        col.addWidget(self.info)
        self.on_open_file = None

    def show_listing(self, path: str, entries: list[remote.Entry]):
        self.path, self.entries = path, entries
        rows = [Row("..", is_dir=True, kind="up")] if path != "/" else []
        rows += [Row(e.name, e.size, e.mtime, e.is_dir, e.perms, e.owner, e.is_link) for e in entries]
        self.model.set_rows(rows)
        self.box.setEditText(path)
        self._tree_add(path, [e.name for e in entries if e.is_dir])
        self._summary()

    def _node(self, path: str) -> QTreeWidgetItem:
        if path in self.nodes:
            return self.nodes[path]
        if path == "/":
            it = QTreeWidgetItem(["/"])
            it.setIcon(0, file_icon("server"))
            self.tree.addTopLevelItem(it)
        else:
            parent = self._node(remote.parent(path))
            it = QTreeWidgetItem([posixpath.basename(path)])
            it.setIcon(0, file_icon("folder"))
            parent.addChild(it)
            parent.setExpanded(True)
        it.setData(0, Qt.UserRole, path)
        self.nodes[path] = it
        return it

    def _tree_add(self, path: str, subdirs: list[str]):
        node = self._node(path)
        for name in sorted(subdirs, key=str.lower):
            self._node(remote.join(path, name))
        node.setExpanded(True)
        self.tree.setCurrentItem(node)

    def clear(self):
        self.path, self.entries = "", []
        self.model.set_rows([])
        for top in [self.tree.takeTopLevelItem(0) for _ in range(self.tree.topLevelItemCount())]:
            del top
        self.nodes.clear()
        self.box.setEditText("")
        self.info.setText("Not connected to any server")

    def _double(self, index):
        r = self.model.rows[index.row()]
        if r.kind == "up":
            self.navigate_requested.emit(remote.parent(self.path))
        elif r.is_dir:
            self.navigate_requested.emit(remote.join(self.path, r.name))
        elif self.on_open_file:
            self.on_open_file([r])

    def selected(self) -> list[Row]:
        return [self.model.rows[i.row()] for i in self.list.selectionModel().selectedRows()
                if self.model.rows[i.row()].kind != "up"]

    def full(self, name: str) -> str:
        return remote.join(self.path, name)

    def entry(self, name: str) -> remote.Entry | None:
        return next((e for e in self.entries if e.name == name), None)

    def _summary(self):
        if self.path:
            self.info.setText(summary(self.model.rows, self.selected()))


def compare(local: ListModel, remote_model: ListModel) -> None:
    """Directory comparison: files whose size differs (or only on one side) are marked on both sides."""
    lf = {r.name: r for r in local.rows if r.kind in ("file", "folder")}
    rf = {r.name: r for r in remote_model.rows if r.kind in ("file", "folder")}
    for mine, other, model in ((lf, rf, local), (rf, lf, remote_model)):
        marks = {}
        for name, r in mine.items():
            o = other.get(name)
            if o is None:
                marks[name] = "only"
            elif not r.is_dir and (o.size != r.size):
                marks[name] = "differs"
        model.beginResetModel()
        model.marks = marks
        model.endResetModel()


def clear_compare(*models: ListModel) -> None:
    for m in models:
        m.beginResetModel()
        m.marks = {}
        m.endResetModel()

