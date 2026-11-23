"""Site Manager (Ctrl+S), as FileZilla's: saved sites on the left, the selected one's settings on the right.
Sites are kept by sites.py (settings as JSON, passwords in Windows Credential Manager)."""

from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import remote, sites, theme
from .widgets import Header, file_icon

PROTOCOLS = [("ftp", "FTP - File Transfer Protocol"), ("sftp", "SFTP - SSH File Transfer Protocol")]
LOGONS = [("anonymous", "Anonymous"), ("normal", "Normal"), ("ask", "Ask for password"), ("key", "Key file")]


def _label(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


class SiteManager(QDialog):
    def __init__(self, parent=None, select: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Site Manager")
        self.resize(1040, 640)
        self.sites = sites.load_sites()
        self.passwords = {s["id"]: sites.get_password(s["id"]) for s in self.sites}
        self.current: dict | None = None
        self.chosen: remote.Site | None = None  # Connect: the site to connect to
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header("SITE MANAGER"))
        body = QHBoxLayout()
        body.setContentsMargins(20, 12, 20, 0)
        left = QVBoxLayout()
        left.addWidget(_label("Select entry"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setStyleSheet(f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; "
                                "color: #FFFFFF; } QTreeView::branch:selected { background: transparent; }")
        self.root_item = QTreeWidgetItem(["My Sites"])
        self.root_item.setIcon(0, file_icon("folder"))
        self.tree.addTopLevelItem(self.root_item)
        self.tree.currentItemChanged.connect(self._picked)
        self.tree.itemChanged.connect(self._renamed)
        left.addWidget(self.tree, 1)
        grid = QGridLayout()
        for i, (t, fn) in enumerate((("New site", self.new_site), ("Duplicate", self.duplicate),
                                     ("Rename", self.rename), ("Delete", self.delete))):
            b = QPushButton(t)
            b.clicked.connect(fn)
            grid.addWidget(b, i // 2, i % 2)
        left.addLayout(grid)
        body.addLayout(left, 2)

        self.tabs = QTabWidget()
        general = QWidget()
        g = QGridLayout(general)
        g.setVerticalSpacing(10)
        self.protocol = QComboBox()
        for key, text in PROTOCOLS:
            self.protocol.addItem(text, key)
        self.protocol.currentIndexChanged.connect(self._protocol_changed)
        g.addWidget(_label("Protocol"), 0, 0)
        g.addWidget(self.protocol, 0, 1, 1, 3)
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.port.setFixedWidth(90)
        g.addWidget(_label("Host"), 1, 0)
        g.addWidget(self.host, 1, 1)
        g.addWidget(_label("Port"), 1, 2)
        g.addWidget(self.port, 1, 3)
        self.encryption = QComboBox()
        for key, text in remote.ENCRYPTIONS.items():
            self.encryption.addItem(text, key)
        self.enc_label = _label("Encryption")
        g.addWidget(self.enc_label, 2, 0)
        g.addWidget(self.encryption, 2, 1, 1, 3)
        self.logon = QComboBox()
        self.logon.currentIndexChanged.connect(self._logon_changed)
        g.addWidget(_label("Logon type"), 3, 0)
        g.addWidget(self.logon, 3, 1, 1, 3)
        self.user = QLineEdit()
        g.addWidget(_label("User"), 4, 0)
        g.addWidget(self.user, 4, 1, 1, 3)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.pw_label = _label("Password")
        g.addWidget(self.pw_label, 5, 0)
        g.addWidget(self.password, 5, 1, 1, 3)
        self.key_file = QLineEdit()
        self.key_browse = QPushButton("Browse...")
        self.key_browse.clicked.connect(self._browse_key)
        self.key_label = _label("Key file")
        g.addWidget(self.key_label, 6, 0)
        g.addWidget(self.key_file, 6, 1, 1, 2)
        g.addWidget(self.key_browse, 6, 3)
        note = QLabel("Passwords are kept in Windows Credential Manager, not in PR7-F's settings."
                      if sites.can_store_passwords() else
                      "No credential store here: passwords aren't kept; PR7-F asks for them when connecting.")
        note.setProperty("role", "dim")
        note.setWordWrap(True)
        g.addWidget(note, 7, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setRowStretch(8, 1)
        self.tabs.addTab(general, "GENERAL")
        adv = QWidget()
        a = QGridLayout(adv)
        self.local_dir = QLineEdit()
        self.remote_dir = QLineEdit()
        a.addWidget(_label("Default local directory"), 0, 0)
        a.addWidget(self.local_dir, 0, 1)
        a.addWidget(_label("Default remote directory"), 1, 0)
        a.addWidget(self.remote_dir, 1, 1)
        a.setRowStretch(2, 1)
        self.tabs.addTab(adv, "ADVANCED")
        body.addWidget(self.tabs, 3)
        root.addLayout(body, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 14, 20, 0)
        buttons.addStretch(1)
        for text, fn in (("Connect", self.connect_site), ("OK", self.accept), ("Cancel", self.reject)):
            b = QPushButton(text)
            b.setMinimumWidth(96)
            b.setDefault(text == "Connect")
            b.clicked.connect(fn)
            buttons.addWidget(b)
        root.addLayout(buttons)
        self.items: dict[str, QTreeWidgetItem] = {}
        for s in self.sites:
            self._add_item(s)
        self.root_item.setExpanded(True)
        first = self.items.get(select) or (self.items[self.sites[0]["id"]] if self.sites else None)
        if first:
            self.tree.setCurrentItem(first)
        self._enable(first is not None)

    # -------------------------------------------------------------------------- the list
    def _add_item(self, s: dict) -> QTreeWidgetItem:
        it = QTreeWidgetItem([s["name"]])
        it.setIcon(0, file_icon("server"))
        it.setData(0, Qt.UserRole, s["id"])
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.root_item.addChild(it)
        self.items[s["id"]] = it
        return it

    def _site(self, item) -> dict | None:
        sid = item.data(0, Qt.UserRole) if item is not None else None
        return next((s for s in self.sites if s["id"] == sid), None)

    def _picked(self, cur, prev):
        self._store()
        self.current = self._site(cur)
        self._enable(self.current is not None)
        if self.current:
            self._show(self.current)

    def _renamed(self, item, _col):
        s = self._site(item)
        if s:
            s["name"] = item.text(0).strip() or s["name"]

    def new_site(self):
        self._store()
        s = sites.new_site(self._unique("New site"))
        self.sites.append(s)
        self.passwords[s["id"]] = ""
        it = self._add_item(s)
        self.tree.setCurrentItem(it)
        self.tree.editItem(it, 0)
        return s

    def duplicate(self):
        if not self.current:
            return
        self._store()
        s = copy.deepcopy(self.current)
        s["id"] = sites.new_site()["id"]
        s["name"] = self._unique(self.current["name"] + " (copy)")
        self.sites.append(s)
        self.passwords[s["id"]] = self.passwords.get(self.current["id"], "")
        self.tree.setCurrentItem(self._add_item(s))

    def rename(self):
        it = self.tree.currentItem()
        if it is not None and self._site(it):
            self.tree.editItem(it, 0)

    def delete(self):
        if not self.current:
            return
        if QMessageBox.question(self, "Site Manager", f'Delete the site "{self.current["name"]}"?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        sid = self.current["id"]
        self.current = None
        self.sites = [s for s in self.sites if s["id"] != sid]
        self.deleted = getattr(self, "deleted", []) + [sid]
        it = self.items.pop(sid)
        self.root_item.removeChild(it)

    def _unique(self, name: str) -> str:
        names = {s["name"] for s in self.sites}
        n, out = 2, name
        while out in names:
            out = f"{name} ({n})"
            n += 1
        return out

    # -------------------------------------------------------------------------- the form
    def _enable(self, on: bool):
        self.tabs.setEnabled(on)

    def _show(self, s: dict):
        self.protocol.setCurrentIndex(max(0, [k for k, _ in PROTOCOLS].index(s.get("protocol", "ftp"))))
        self._protocol_changed()
        self.host.setText(s.get("host", ""))
        self.port.setText(str(s.get("port") or ""))
        self.encryption.setCurrentIndex(list(remote.ENCRYPTIONS).index(s.get("encryption", "auto")))
        keys = [self.logon.itemData(i) for i in range(self.logon.count())]
        self.logon.setCurrentIndex(keys.index(s.get("logon", "normal")) if s.get("logon") in keys else 1)
        self.user.setText(s.get("user", ""))
        self.password.setText(self.passwords.get(s["id"], ""))
        self.key_file.setText(s.get("key_file", ""))
        self.local_dir.setText(s.get("local_dir", ""))
        self.remote_dir.setText(s.get("remote_dir", ""))
        self._logon_changed()

    def _store(self):
        s = self.current
        if not s:
            return
        s["protocol"] = self.protocol.currentData()
        s["host"] = self.host.text().strip()
        s["port"] = int(self.port.text()) if self.port.text().strip().isdigit() else 0
        s["encryption"] = self.encryption.currentData()
        s["logon"] = self.logon.currentData()
        s["user"] = self.user.text().strip()
        s["key_file"] = self.key_file.text().strip()
        s["local_dir"] = self.local_dir.text().strip()
        s["remote_dir"] = self.remote_dir.text().strip()
        self.passwords[s["id"]] = self.password.text() if s["logon"] in ("normal", "key") else ""

    def _protocol_changed(self, *_):
        sftp = self.protocol.currentData() == "sftp"
        self.encryption.setVisible(not sftp)
        self.enc_label.setVisible(not sftp)
        self.port.setPlaceholderText("22" if sftp else "21")
        cur = self.logon.currentData()
        self.logon.blockSignals(True)
        self.logon.clear()
        for key, text in LOGONS:
            if key == "key" and not sftp:
                continue
            if key == "anonymous" and sftp:
                continue
            self.logon.addItem(text, key)
        keys = [self.logon.itemData(i) for i in range(self.logon.count())]
        self.logon.setCurrentIndex(keys.index(cur) if cur in keys else keys.index("normal"))
        self.logon.blockSignals(False)
        self._logon_changed()

    def _logon_changed(self, *_):
        logon = self.logon.currentData()
        self.user.setEnabled(logon != "anonymous")
        self.password.setEnabled(logon in ("normal", "key"))
        self.pw_label.setText("PASSPHRASE" if logon == "key" else "PASSWORD")
        for w in (self.key_file, self.key_browse, self.key_label):
            w.setVisible(logon == "key")

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Key file", "", "Private keys (*)")
        if path:
            self.key_file.setText(path)

    # -------------------------------------------------------------------------- closing
    def save(self):
        self._store()
        for sid in getattr(self, "deleted", []):
            sites.delete_password(sid)
        for s in self.sites:
            sites.set_password(s["id"], self.passwords.get(s["id"], ""))
        sites.save_sites(self.sites)

    def accept(self):
        self.save()
        super().accept()

    def connect_site(self):
        self.save()
        if not self.current or not self.current.get("host"):
            QMessageBox.information(self, "Site Manager", "Type the server's address in Host first.")
            return
        self.chosen = sites.to_site(self.current)
        super().accept()
