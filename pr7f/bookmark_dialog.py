"""Add bookmark (Ctrl+B) and Manage bookmarks (Ctrl+Shift+B), as FileZilla's."""

from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import bookmarks, theme
from .bookmarks import Bookmark
from .widgets import Header, file_icon


def _shell(dlg, header):
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 16)
    root.addWidget(Header(header))
    body = QVBoxLayout()
    body.setContentsMargins(20, 12, 20, 0)
    root.addLayout(body, 1)
    return body


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


class BookmarkForm(QWidget):
    """Name, local folder, remote folder, synchronised browsing, comparison."""

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.local = QLineEdit()
        self.remote = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        for r, (label, w) in enumerate((("Name", self.name), ("Local directory", self.local),
                                         ("Remote directory", self.remote))):
            g.addWidget(_field(label), r, 0)
            g.addWidget(w, r, 1)
        g.addWidget(browse, 1, 2)
        self.sync = QCheckBox("Use synchronised browsing")
        self.compare = QCheckBox("Directory comparison")
        g.addWidget(self.sync, 3, 1)
        g.addWidget(self.compare, 4, 1)
        hint = QLabel("Synchronised browsing needs both directories.")
        hint.setProperty("role", "dim")
        g.addWidget(hint, 5, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(6, 1)  # the space below the form, not between its rows

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Local directory", self.local.text())
        if d:
            self.local.setText(d)

    def show_bookmark(self, b: Bookmark | None):
        self.setEnabled(b is not None)
        b = b or Bookmark("")
        self.name.setText(b.name)
        self.local.setText(b.local)
        self.remote.setText(b.remote)
        self.sync.setChecked(b.sync)
        self.compare.setChecked(b.compare)

    def value(self) -> Bookmark:
        local, rem = self.local.text().strip(), self.remote.text().strip()
        return Bookmark(self.name.text().strip() or "Bookmark", local, rem, self.sync.isChecked() and bool(local and rem),
                        self.compare.isChecked())


class AddBookmarkDialog(QDialog):
    def __init__(self, local: str, remote: str, site_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New bookmark")
        self.resize(720, 420)
        self.site_id = site_id
        body = _shell(self, "NEW BOOKMARK")
        kind = QHBoxLayout()
        kind.addWidget(_field("Type"))
        self.globl = QRadioButton("Global bookmark")
        self.site = QRadioButton(f"Site-specific bookmark ({bookmarks.site_name(site_id)})" if site_id else
                                 "Site-specific bookmark (connect from the Site Manager first)")
        self.site.setEnabled(bool(site_id))
        (self.site if site_id else self.globl).setChecked(True)  # FileZilla: site-specific when it can be
        kind.addWidget(self.globl)
        kind.addWidget(self.site)
        kind.addStretch(1)
        body.addLayout(kind)
        self.form = BookmarkForm(self)
        self.form.show_bookmark(Bookmark("", local, remote))
        body.addWidget(self.form)
        body.addStretch(1)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        body.addWidget(b)

    def accept(self):
        if not self.form.name.text().strip():
            self.form.name.setFocus()
            return
        self.save()
        super().accept()

    def save(self) -> Bookmark:
        b = self.form.value()
        if self.site.isChecked() and self.site_id:
            items = bookmarks.load_site(self.site_id)
            b.name = bookmarks.unique(b.name, items)
            bookmarks.save_site(self.site_id, items + [b])
        else:
            items = bookmarks.load_global()
            b.name = bookmarks.unique(b.name, items)
            bookmarks.save_global(items + [b])
        self.saved = b
        return b


class ManageBookmarksDialog(QDialog):
    """Every bookmark: global ones, and the connected site's; edit, new, duplicate, delete."""

    def __init__(self, site_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bookmarks")
        self.resize(940, 520)
        self.site_id = site_id
        self.lists = {"global": bookmarks.load_global(), "site": bookmarks.load_site(site_id) if site_id else []}
        self.current: tuple[str, int] | None = None
        body = _shell(self, "BOOKMARKS")
        main = QHBoxLayout()
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setStyleSheet(f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; "
                                "color: #FFFFFF; } QTreeView::branch:selected { background: transparent; }")
        self.tree.currentItemChanged.connect(self._picked)
        left.addWidget(self.tree, 1)
        g = QGridLayout()
        for i, (text, fn) in enumerate((("New bookmark", self.new), ("Duplicate", self.duplicate),
                                        ("Delete", self.delete))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, 0, i)
        left.addLayout(g)
        main.addLayout(left, 2)
        self.form = BookmarkForm(self)
        main.addWidget(self.form, 3)
        body.addLayout(main, 1)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        body.addWidget(b)
        self._fill(("global", 0) if self.lists["global"] else ("site", 0))

    def _fill(self, select=None):
        self.tree.blockSignals(True)
        while self.tree.topLevelItemCount():
            self.tree.takeTopLevelItem(0)
        groups = [("global", "Global bookmarks")]
        if self.site_id:
            groups.append(("site", f"Site-specific bookmarks ({bookmarks.site_name(self.site_id)})"))
        chosen = None
        for kind, title in groups:
            top = QTreeWidgetItem([title])
            top.setIcon(0, file_icon("folder"))
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(top)
            for i, b in enumerate(self.lists[kind]):
                it = QTreeWidgetItem([b.name])
                it.setIcon(0, file_icon("server" if kind == "site" else "drive"))
                it.setData(0, Qt.UserRole, (kind, i))
                top.addChild(it)
                if select == (kind, i):
                    chosen = it
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.current = None
        if chosen is not None:
            self.tree.setCurrentItem(chosen)
        else:
            self.form.show_bookmark(None)

    def _store(self):
        if self.current is not None:
            kind, i = self.current
            if i < len(self.lists[kind]):
                self.lists[kind][i] = self.form.value()

    def _picked(self, cur, _prev):
        self._store()
        key = cur.data(0, Qt.UserRole) if cur is not None else None
        self.current = tuple(key) if key else None
        if self.current:
            kind, i = self.current
            self.form.show_bookmark(self.lists[kind][i])
        else:
            self.form.show_bookmark(None)

    def new(self):
        self._store()
        kind = self.current[0] if self.current else ("site" if self.site_id else "global")
        items = self.lists[kind]
        items.append(Bookmark(bookmarks.unique("New bookmark", items)))
        self._fill((kind, len(items) - 1))

    def duplicate(self):
        if self.current is None:
            return
        self._store()
        kind, i = self.current
        b = copy.deepcopy(self.lists[kind][i])
        b.name = bookmarks.unique(b.name + " (copy)", self.lists[kind])
        self.lists[kind].append(b)
        self._fill((kind, len(self.lists[kind]) - 1))

    def delete(self):
        if self.current is None:
            return
        kind, i = self.current
        del self.lists[kind][i]
        self.current = None
        self._fill((kind, min(i, len(self.lists[kind]) - 1)) if self.lists[kind] else None)

    def accept(self):
        self._store()
        bookmarks.save_global(self.lists["global"])
        if self.site_id:
            bookmarks.save_site(self.site_id, self.lists["site"])
        super().accept()
