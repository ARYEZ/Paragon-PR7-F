"""FileZilla's questions and small dialogs, in the family look: target file exists, unknown host key, unknown
certificate, file permissions, settings."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QGroupBox, QLabel, QLineEdit, QRadioButton, QSpinBox, QVBoxLayout)

from . import remote, settings, transfers
from .widgets import Header


def _shell(dlg: QDialog, header: str) -> QVBoxLayout:
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 16)
    root.addWidget(Header(header))
    body = QVBoxLayout()
    body.setContentsMargins(20, 12, 20, 0)
    root.addLayout(body, 1)
    return body


def _dim(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def _ok_cancel(dlg: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.button(QDialogButtonBox.Ok).setText(ok_text)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class FileExistsDialog(QDialog):
    """Target file already exists: both files, and what to do (FileZilla's choices)."""

    def __init__(self, ex: transfers.Exists, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Target file already exists")
        self.resize(720, 560)
        body = _shell(self, "FILE EXISTS")
        it = ex.item
        source, target = (it.local, it.remote) if it.direction == "upload" else (it.remote, it.local)
        body.addWidget(QLabel("The target file already exists. Please choose an action."))
        g = QGridLayout()
        for r, (label, path, size, mtime) in enumerate((("Source", source, ex.source_size, ex.source_mtime),
                                                        ("Target", target, ex.target_size, ex.target_mtime))):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            g.addWidget(lab, r, 0, Qt.AlignTop)
            g.addWidget(_dim(f"{path}\n{size:,} bytes  ·  {remote.fmt_time(mtime)}"), r, 1)
        g.setColumnStretch(1, 1)
        body.addLayout(g)
        box = QGroupBox("ACTION")
        bl = QVBoxLayout(box)
        self.group = QButtonGroup(self)
        last = settings.get("exists_last", "overwrite")
        for key, text in transfers.ACTIONS.items():
            rb = QRadioButton(text)
            rb.setProperty("action", key)
            rb.setChecked(key == last)
            self.group.addButton(rb)
            bl.addWidget(rb)
            if key == "rename":
                self.new_name = QLineEdit(os.path.basename(target.rstrip("/")))
                self.new_name.setEnabled(rb.isChecked())
                rb.toggled.connect(self.new_name.setEnabled)
                bl.addWidget(self.new_name)
        body.addWidget(box)
        self.all = QCheckBox("Always use this action (for the rest of the queue)")
        body.addWidget(self.all)
        body.addWidget(_ok_cancel(self))

    def answer(self):
        action = self.group.checkedButton().property("action")
        settings.set("exists_last", action)
        if action == "rename":
            return "rename", self.new_name.text().strip() or "renamed"
        return action, self.all.isChecked()


class HostKeyDialog(QDialog):
    """Unknown (or changed) host key: the fingerprint, and trust it once or always."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        changed = info.get("changed")
        self.setWindowTitle("Host key mismatch" if changed else "Unknown host key")
        self.resize(680, 380)
        body = _shell(self, "HOST KEY CHANGED" if changed else "UNKNOWN HOST KEY")
        if changed:
            warn = QLabel("WARNING: the server's host key isn't the one remembered for it. Someone may be "
                          "pretending to be the server, or its administrator changed the key.")
            warn.setProperty("role", "error")
            warn.setWordWrap(True)
            body.addWidget(warn)
        else:
            body.addWidget(_dim("The server's host key is unknown. Trust it only if you're sure it's the right "
                                "server (compare the fingerprint with the one its administrator gives)."))
        body.addWidget(_dim(f"Host: {info['host']}:{info['port']}\nKey type: {info['kind']}\n"
                            f"Fingerprint: {info['fingerprint']}"))
        self.always = QCheckBox("Always trust this host, add this key to the cache")
        self.always.setChecked(not changed)
        body.addWidget(self.always)
        body.addStretch(1)
        body.addWidget(_ok_cancel(self))

    def answer(self):
        return "always" if self.always.isChecked() else "once"


class CertDialog(QDialog):
    """FTPS: a certificate Windows doesn't vouch for (most small servers' are self-signed)."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unknown certificate")
        self.resize(680, 360)
        body = _shell(self, "UNKNOWN CERTIFICATE")
        body.addWidget(_dim("The server's certificate is unknown. Trust it only if you're sure it's the right "
                            "server: the connection is encrypted either way."))
        body.addWidget(_dim(f"Host: {info['host']}\nSHA-256 fingerprint: {info['sha256']}"))
        self.always = QCheckBox("Always trust this certificate in future sessions")
        self.always.setChecked(True)
        body.addWidget(self.always)
        body.addStretch(1)
        body.addWidget(_ok_cancel(self))

    def answer(self):
        return "always" if self.always.isChecked() else "once"


class ChmodDialog(QDialog):
    """Change file attributes: read / write / execute for owner, group and public, and the numeric value."""

    def __init__(self, names: list[str], mode: int | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change file attributes")
        self.resize(560, 420)
        body = _shell(self, "FILE ATTRIBUTES")
        body.addWidget(_dim(f"Please select the new attributes for {', '.join(names[:3])}"
                            + (" ..." if len(names) > 3 else "") + "."))
        self.checks = {}
        mode = 0o644 if mode is None else mode
        for who, shift in (("Owner", 6), ("Group", 3), ("Public", 0)):
            box = QGroupBox(f"{who.upper()} PERMISSIONS")
            g = QGridLayout(box)
            for c, (what, bit) in enumerate((("Read", 4), ("Write", 2), ("Execute", 1))):
                cb = QCheckBox(what)
                cb.setChecked(bool(mode & (bit << shift)))
                cb.toggled.connect(self._from_checks)
                self.checks[(shift, bit)] = cb
                g.addWidget(cb, 0, c)
            body.addWidget(box)
        g = QGridLayout()
        lab = QLabel("NUMERIC VALUE")
        lab.setProperty("role", "field")
        g.addWidget(lab, 0, 0)
        self.numeric = QLineEdit(f"{mode:03o}")
        self.numeric.setMaxLength(4)
        self.numeric.textEdited.connect(self._from_text)
        g.addWidget(self.numeric, 0, 1)
        body.addLayout(g)
        body.addWidget(_ok_cancel(self))

    def mode(self) -> int:
        return sum(bit << shift for (shift, bit), cb in self.checks.items() if cb.isChecked())

    def _from_checks(self, *_):
        self.numeric.setText(f"{self.mode():03o}")

    def _from_text(self, text):
        try:
            m = int(text, 8)
        except ValueError:
            return
        for (shift, bit), cb in self.checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(m & (bit << shift)))
            cb.blockSignals(False)


ALREADY = {"ask": "Ask what to do", "new_tab": "Connect in a new tab", "replace": "Abort the previous connection"}


class AlreadyConnectedDialog(QDialog):
    """FileZilla's question when the tab is already connected: a new tab, or replace this tab's connection."""

    def __init__(self, current: str, new: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Already connected")
        self.resize(620, 330)
        body = _shell(self, "ALREADY CONNECTED")
        body.addWidget(QLabel(f"You are already connected to {current}. What do you want to do with {new}?"))
        self.new_tab = QRadioButton("Connect in a new tab")
        self.replace = QRadioButton("Abort the previous connection and connect in this tab")
        self.new_tab.setChecked(True)
        body.addWidget(self.new_tab)
        body.addWidget(self.replace)
        self.always = QCheckBox("Always perform this action (Edit > Settings changes it)")
        body.addWidget(self.always)
        body.addStretch(1)
        body.addWidget(_ok_cancel(self))

    def answer(self) -> str:
        choice = "new_tab" if self.new_tab.isChecked() else "replace"
        if self.always.isChecked():
            settings.set("already_connected", choice)
        return choice


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 360)
        body = _shell(self, "SETTINGS")
        box = QGroupBox("TRANSFERS")
        g = QGridLayout(box)
        lab = QLabel("MAXIMUM SIMULTANEOUS TRANSFERS")
        lab.setProperty("role", "field")
        g.addWidget(lab, 0, 0)
        self.workers = QSpinBox()
        self.workers.setRange(1, 10)
        self.workers.setValue(settings.get_int("transfers", 2))
        g.addWidget(self.workers, 0, 1)
        lab = QLabel("WHEN ALREADY CONNECTED")
        lab.setProperty("role", "field")
        g.addWidget(lab, 1, 0)
        self.already = QComboBox()
        for k, text in ALREADY.items():
            self.already.addItem(text, k)
        self.already.setCurrentIndex(list(ALREADY).index(settings.get("already_connected", "ask"))
                                     if settings.get("already_connected", "ask") in ALREADY else 0)
        g.addWidget(self.already, 1, 1)
        body.addWidget(box)
        f = QGroupBox("FINISH")
        fl = QGridLayout(f)
        self.finish = QComboBox()
        self.finish.addItems(["OBSIDIAN", "AURORA"])
        self.finish.setCurrentText(settings.get("finish", "obsidian").upper())
        fl.addWidget(self.finish, 0, 0)
        body.addWidget(f)
        body.addStretch(1)
        body.addWidget(_ok_cancel(self))

    def apply(self):
        settings.set("transfers", self.workers.value())
        settings.set("already_connected", self.already.currentData())
        settings.set("finish", self.finish.currentText().lower())
