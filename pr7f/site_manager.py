"""Site Manager (Ctrl+S), as FileZilla's: saved servers on the left, their settings on the right. (Mock-up.)"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .widgets import Header, file_icon

PROTOCOLS = ["FTP - File Transfer Protocol", "SFTP - SSH File Transfer Protocol"]
ENCRYPTIONS = ["Use explicit FTP over TLS if available", "Require explicit FTP over TLS",
               "Require implicit FTP over TLS", "Only use plain FTP (insecure)"]
LOGONS = ["Anonymous", "Normal", "Ask for password", "Interactive", "Key file"]


def _label(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


class SiteManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Site Manager")
        self.resize(1040, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 16)
        root.addWidget(Header("SITE MANAGER"))
        body = QHBoxLayout()
        body.setContentsMargins(20, 12, 20, 0)
        left = QVBoxLayout()
        left.addWidget(_label("Select entry"))
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setIconSize(QSize(18, 18))
        mine = QTreeWidgetItem(["My Sites"])
        mine.setIcon(0, file_icon("folder"))
        tree.addTopLevelItem(mine)
        current = None
        for name in ("Paragon website", "Paragon NAS (SFTP)", "Client uploads"):
            it = QTreeWidgetItem([name])
            it.setIcon(0, file_icon("server"))
            mine.addChild(it)
            current = current or it
        mine.setExpanded(True)
        tree.setCurrentItem(current)
        from . import theme
        tree.setStyleSheet(f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; "
                           "color: #FFFFFF; } QTreeView::branch:selected { background: transparent; }")
        left.addWidget(tree, 1)
        grid = QGridLayout()
        for i, t in enumerate(("New site", "New folder", "New bookmark", "Rename", "Delete", "Duplicate")):
            grid.addWidget(QPushButton(t), i // 2, i % 2)
        left.addLayout(grid)
        body.addLayout(left, 2)

        tabs = QTabWidget()
        general = QWidget()
        g = QGridLayout(general)
        g.setVerticalSpacing(10)
        protocol = QComboBox()
        protocol.addItems(PROTOCOLS)
        g.addWidget(_label("Protocol"), 0, 0)
        g.addWidget(protocol, 0, 1, 1, 3)
        g.addWidget(_label("Host"), 1, 0)
        g.addWidget(QLineEdit("ftp.paragon-productions.example"), 1, 1)
        g.addWidget(_label("Port"), 1, 2)
        port = QLineEdit("")
        port.setPlaceholderText("21")
        port.setFixedWidth(80)
        g.addWidget(port, 1, 3)
        enc = QComboBox()
        enc.addItems(ENCRYPTIONS)
        g.addWidget(_label("Encryption"), 2, 0)
        g.addWidget(enc, 2, 1, 1, 3)
        logon = QComboBox()
        logon.addItems(LOGONS)
        logon.setCurrentIndex(1)
        g.addWidget(_label("Logon type"), 3, 0)
        g.addWidget(logon, 3, 1, 1, 3)
        g.addWidget(_label("User"), 4, 0)
        g.addWidget(QLineEdit("paragon"), 4, 1, 1, 3)
        pw = QLineEdit("secret")
        pw.setEchoMode(QLineEdit.Password)
        g.addWidget(_label("Password"), 5, 0)
        g.addWidget(pw, 5, 1, 1, 3)
        note = QLabel("Passwords are kept in Windows Credential Manager, not in PR7-F's settings.")
        note.setProperty("role", "dim")
        g.addWidget(note, 6, 1, 1, 3)
        g.addWidget(_label("Comments"), 7, 0, Qt.AlignTop)
        g.addWidget(QLineEdit("Website and the music downloads"), 7, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setRowStretch(8, 1)
        tabs.addTab(general, "GENERAL")
        adv = QWidget()
        a = QGridLayout(adv)
        a.addWidget(_label("Default local directory"), 0, 0)
        a.addWidget(QLineEdit("C:\\Users\\You\\Music\\Paragon"), 0, 1)
        a.addWidget(_label("Default remote directory"), 1, 0)
        a.addWidget(QLineEdit("/public_html/music"), 1, 1)
        a.setRowStretch(2, 1)
        tabs.addTab(adv, "ADVANCED")
        tr = QWidget()
        t = QGridLayout(tr)
        t.addWidget(_label("Transfer mode"), 0, 0)
        mode = QComboBox()
        mode.addItems(["Default", "Active", "Passive"])
        t.addWidget(mode, 0, 1)
        t.addWidget(_label("Maximum connections"), 1, 0)
        n = QSpinBox()
        n.setRange(1, 10)
        n.setValue(2)
        t.addWidget(n, 1, 1)
        t.setRowStretch(2, 1)
        tabs.addTab(tr, "TRANSFER SETTINGS")
        body.addWidget(tabs, 3)
        root.addLayout(body, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 14, 20, 0)
        buttons.addStretch(1)
        for text in ("Connect", "OK", "Cancel"):
            b = QPushButton(text)
            b.setMinimumWidth(96)
            b.setDefault(text == "Connect")
            buttons.addWidget(b)
        root.addLayout(buttons)
