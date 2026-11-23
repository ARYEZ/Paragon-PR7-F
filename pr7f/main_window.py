"""The window, as FileZilla's: quick-connect bar, message log, local and remote sites side by side, transfer queue.

The remote pane's connection (Browser) and the queue's workers (TransferQueue, each with its own connection) run on
their own threads; questions they ask (host key, certificate, file exists) come here through Asker. `self.answers`
can replace the dialogs (tests).
"""

from __future__ import annotations

import os
import posixpath
import shutil
import tempfile

from PySide6.QtCore import QAbstractTableModel, QFileSystemWatcher, QModelIndex, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPainter, QPen, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QStatusBar, QStyledItemDelegate, QTabWidget, QToolButton, QTreeView,
                               QVBoxLayout, QWidget)

from . import __version__, remote, settings, sites, theme
from .browser import Asker, Browser
from .panes import LocalPane, RemotePane, clear_compare, compare
from .transfers import TransferQueue
from .widgets import Header, Toolbar, draw_icon

LOG_COLOURS = {"Status": "TEXT_DIM", "Command": "TEXT", "Response": "LED_ORANGE", "Error": "METER_RED"}
QUEUE_COLUMNS = ["Server/Local file", "Direction", "Remote file", "Size", "Status"]


def recycle(paths: list[str]) -> None:
    """Delete local files as Explorer does: to the Recycle Bin on Windows (FileZilla's way); elsewhere for good."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = SHFILEOPSTRUCTW(None, 3, "\0".join(paths) + "\0\0", None, 0x0040 | 0x0010 | 0x0400 | 0x0004,
                             False, None, None)  # FO_DELETE, ALLOWUNDO | NOCONFIRMATION | NOERRORUI | SILENT
        if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)):
            raise OSError("The files couldn't be moved to the Recycle Bin.")
        return
    for p in paths:
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)


class QueueModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows = []

    def set_rows(self, rows):
        if [r.id for r in rows] == [r.id for r in self.rows]:
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(QUEUE_COLUMNS) - 1))
            return
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(QUEUE_COLUMNS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return QUEUE_COLUMNS[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.rows[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            if c == 0:
                return it.local
            if c == 1:
                return "→" if it.direction == "upload" else "←"
            if c == 2:
                return it.remote
            if c == 3:
                return "" if it.is_dir else f"{it.size:,}"
            if c == 4:
                return {"queued": "", "active": "Transferring", "done": "Done", "skipped": "Skipped",
                        "failed": it.error}.get(it.status, it.status)
        if role == Qt.TextAlignmentRole and c == 3:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and c == 4 and it.status == "failed":
            return QColor(theme.METER_RED)
        return None


class ProgressDelegate(QStyledItemDelegate):
    """The Status column of a running transfer: a family-gradient bar with the speed."""

    def paint(self, p, option, index):
        it = index.model().rows[index.row()]
        if it.status != "active" or it.is_dir:
            super().paint(p, option, index)
            return
        frac = min(1.0, it.transferred / it.size) if it.size else 0.0
        r = QRectF(option.rect).adjusted(4, 5, -4, -5)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.setBrush(QColor(theme.WIDGET))
        p.drawRoundedRect(r, 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.family_gradient(r.left(), 0, r.right(), 0))
        p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * frac, r.height()), 3, 3)
        p.setPen(QColor("#FFFFFF"))
        speed = it.speed
        left = (it.size - it.transferred) / speed if speed else 0
        extra = f"  ·  {speed / 1048576:.1f} MB/s  ·  {int(left // 60)}:{int(left % 60):02d} left" if speed else ""
        p.drawText(r, Qt.AlignCenter, f"{frac:.0%}{extra}")
        p.restore()


def _queue_view(model) -> QTreeView:
    v = QTreeView()
    v.setRootIsDecorated(False)
    v.setAlternatingRowColors(True)
    v.setSelectionMode(QAbstractItemView.ExtendedSelection)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setUniformRowHeights(True)
    v.setModel(model)
    for i, w in enumerate([440, 100, 420, 110]):
        v.header().resizeSection(i, w)
    v.header().setStretchLastSection(True)
    v.header().setSectionResizeMode(QHeaderView.Interactive)
    v.setItemDelegateForColumn(4, ProgressDelegate(v))
    return v


# Menus: (text with shortcut after a tab, slot) ; "-" separator; slot None: not yet (greyed out).
MENUS = {
    "&File": [("&Site Manager...\tCtrl+S", "site_manager"), ("&Copy current connection to Site Manager...",
                                                              "save_current"), "-", ("E&xit\tCtrl+Q", "close")],
    "&Edit": [("&Settings...", "open_settings")],
    "&View": [("&Refresh\tF5", "refresh"), ("Directory &listing filters...\tCtrl+I", "open_filters"),
              ("&Quick search\tCtrl+F", "quick_search"), ("Directory &comparison", "toggle_compare"), "-",
              ("&Message log", "toggle_log"), ("&Local directory tree", "toggle_local_tree"),
              ("&Remote directory tree", "toggle_remote_tree"), ("Transfer &queue", "toggle_queue")],
    "&Transfer": [("&Process queue\tCtrl+P", "process_queue"), ("&Stop processing", "stop_queue"),
                  ("&Retry failed transfers", "retry_failed"), ("&Clear finished transfers", "clear_finished")],
    "S&erver": [("&Cancel current operation\tCtrl+.", "cancel"), "-", ("&Reconnect\tCtrl+R", "reconnect"),
                ("&Disconnect\tCtrl+D", "disconnect"), "-", ("&Search remote files...\tF3", "search_remote")],
    "&Help": [("&About PR7-F...", "about")],
}
TOOLBAR = {"sitemanager": "site_manager", "log": "toggle_log", "localtree": "toggle_local_tree",
           "remotetree": "toggle_remote_tree", "queue": "toggle_queue", "refresh": "refresh",
           "process": "process_queue", "cancel": "cancel", "disconnect": "disconnect", "reconnect": "reconnect",
           "compare": "toggle_compare", "sync": "toggle_sync", "filter": "open_filters", "search": "search_remote"}


class MainWindow(QMainWindow):
    def __init__(self, start_local: str | None = None):
        super().__init__()
        self.resize(1560, 1000)
        self.site: remote.Site | None = None
        self.queue: TransferQueue | None = None
        self.answers: dict = {}  # kind -> function(payload): replaces a dialog (tests)
        self.asker = Asker({"hostkey": lambda p: self._ask("hostkey", p), "cert": lambda p: self._ask("cert", p),
                            "exists": lambda p: self._ask("exists", p)})
        self.browser = Browser(self.asker)
        self.browser.logged.connect(self.log)
        self.edited: dict[str, str] = {}  # View/Edit: local temp copy -> remote path
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._edited_changed)
        self.sync_base: tuple[str, str] | None = None
        self._build()
        self.local.go(start_local or settings.get("local_dir", "") or os.path.expanduser("~"))
        self._filter_key()
        self.timer = QTimer(self, interval=200)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._done_seen: set[int] = set()
        self._title()

    # -------------------------------------------------------------------------- building
    def _build(self):
        self.actions_by_slot: dict[str, QAction] = {}
        bar = self.menuBar()
        for title, items in MENUS.items():
            m = bar.addMenu(title)
            for it in items:
                if it == "-":
                    m.addSeparator()
                    continue
                text, slot = it
                text, _, sc = text.partition("\t")
                a = QAction(text, self)
                if sc:
                    a.setShortcut(QKeySequence(sc))
                if slot:
                    a.triggered.connect(lambda _=False, s=slot: getattr(self, s)())
                    self.actions_by_slot[slot] = a
                else:
                    a.setEnabled(False)
                    a.setToolTip("Coming in a later version")
                m.addAction(a)
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.header = Header()
        col.addWidget(self.header)
        self.toolbar = Toolbar()
        for name, key in self.toolbar.keys.items():
            if name not in TOOLBAR:
                key.setEnabled(False)
                key.setToolTip(key.toolTip() + " (coming in a later version)")
        for k in ("log", "localtree", "remotetree", "queue"):
            self.toolbar.keys[k].setChecked(True)
        self.toolbar.triggered.connect(lambda n: getattr(self, TOOLBAR[n])() if n in TOOLBAR else None)
        col.addWidget(self.toolbar)
        col.addLayout(self._quickconnect())
        self.main = QSplitter(Qt.Vertical)
        self.main.setContentsMargins(16, 0, 16, 0)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(5000)
        self.main.addWidget(self.logview)
        sites_split = QSplitter(Qt.Horizontal)
        self.local = LocalPane()
        self.local.on_open_file = lambda rows: self.upload(rows, start=True)
        self.local.list.dropped.connect(self._dropped_local)
        self.local.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.local.list.customContextMenuRequested.connect(self._local_menu)
        self.local.navigated.connect(self._local_navigated)
        sites_split.addWidget(self.local)
        self.remote = RemotePane()
        self.remote.on_open_file = lambda rows: self.download(rows, start=True)
        self.remote.navigate_requested.connect(self.navigate)
        self.remote.list.dropped.connect(self._dropped_remote)
        self.remote.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.remote.list.customContextMenuRequested.connect(self._remote_menu)
        sites_split.addWidget(self.remote)
        self.main.addWidget(sites_split)
        from . import filters
        self.filters = filters.load()
        self.local.filters = self.remote.filters = self.filters
        self.local.refilter()
        self.remote.refilter()
        self.queue_tabs = QTabWidget()
        self.models = {k: QueueModel() for k in ("queued", "failed", "done")}
        self.queue_views = {k: _queue_view(m) for k, m in self.models.items()}
        for k, title in (("queued", "QUEUED FILES"), ("failed", "FAILED TRANSFERS"), ("done", "SUCCESSFUL TRANSFERS")):
            self.queue_tabs.addTab(self.queue_views[k], title)
            v = self.queue_views[k]
            v.setContextMenuPolicy(Qt.CustomContextMenu)
            v.customContextMenuRequested.connect(lambda pos, kind=k: self._queue_menu(kind, pos))
        self.main.addWidget(self.queue_tabs)
        self.main.setSizes([170, 560, 200])
        col.addWidget(self.main, 1)
        self.setCentralWidget(central)
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.status_text = QLabel("")
        sb.addWidget(self.status_text, 1)
        self.lock = QLabel()
        sb.addPermanentWidget(self.lock)
        self.enc_text = QLabel("")
        sb.addPermanentWidget(self.enc_text)
        self.queue_text = QLabel("Queue: empty")
        sb.addPermanentWidget(self.queue_text)
        self.setStatusBar(sb)

    def _quickconnect(self):
        qc = QHBoxLayout()
        qc.setContentsMargins(16, 8, 16, 8)
        self.qc = {}
        for key, label, width in (("host", "Host", 300), ("user", "Username", 160), ("password", "Password", 160),
                                  ("port", "Port", 70)):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            qc.addWidget(lab)
            e = QLineEdit()
            e.setFixedWidth(width)
            if key == "password":
                e.setEchoMode(QLineEdit.Password)
            e.returnPressed.connect(self.quickconnect)
            self.qc[key] = e
            qc.addWidget(e)
            qc.addSpacing(8)
        go = QPushButton("Quickconnect")
        go.setDefault(True)
        go.clicked.connect(self.quickconnect)
        qc.addWidget(go)
        hist = QToolButton()
        hist.setArrowType(Qt.DownArrow)
        hist.setToolTip("Recent servers")
        hist.setFixedSize(34, 34)
        hist.clicked.connect(lambda: self._recent_menu(hist))
        qc.addWidget(hist)
        qc.addStretch(1)
        return qc

    # -------------------------------------------------------------------------- the log, questions
    def log(self, kind: str, text: str):
        f = QTextCharFormat()
        f.setForeground(QColor(getattr(theme, LOG_COLOURS.get(kind, "TEXT"))))
        cur = self.logview.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(f"{kind + ':':<10}{text}\n", f)
        self.logview.setTextCursor(cur)
        self.logview.ensureCursorVisible()

    def _ask(self, kind: str, payload):
        if kind in self.answers:
            return self.answers[kind](payload)
        from .dialogs import CertDialog, FileExistsDialog, HostKeyDialog
        dlg = {"hostkey": HostKeyDialog, "cert": CertDialog, "exists": FileExistsDialog}[kind](payload, self)
        return dlg.answer() if dlg.exec() else None

    # -------------------------------------------------------------------------- connecting
    def quickconnect(self):
        try:
            site = remote.parse_quick(self.qc["host"].text(), self.qc["user"].text(), self.qc["password"].text(),
                                      self.qc["port"].text())
        except remote.RemoteError as e:
            QMessageBox.information(self, "Quickconnect", str(e))
            return
        self.connect_to(site)

    def _recent_menu(self, button):
        m = QMenu(self)
        for r in sites.recent():
            text = f"{r['protocol']}://{r['user'] + '@' if r.get('user') else ''}{r['host']}" + (
                f":{r['port']}" if r.get("port") else "")
            m.addAction(text, lambda r=r: self._fill_quick(r))
        if not m.actions():
            m.addAction("No recent servers").setEnabled(False)
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _fill_quick(self, r):
        self.qc["host"].setText((f"{r['protocol']}://" if r["protocol"] != "ftp" else "") + r["host"])
        self.qc["user"].setText(r.get("user", ""))
        self.qc["port"].setText(str(r.get("port") or ""))
        self.qc["password"].setFocus()

    def connect_to(self, site: remote.Site, password_prompt: bool = True):
        if password_prompt and site.logon == "ask" or (site.logon == "normal" and not site.password and site.user
                                                       and site.protocol == "sftp" and password_prompt):
            pw, ok = QInputDialog.getText(self, "Enter password", f"Password for {site.user}@{site.host}:",
                                          QLineEdit.Password)
            if not ok:
                return
            site.password = pw
        if self.queue is not None:
            self.queue.stop()
        self.remote.clear()
        clear_compare(self.local.model, self.remote.model)
        self.site = site
        self.queue = None
        self.status_text.setText(f"Connecting to {site.host}...")
        self.browser.connect(site, self._connected, self._connect_failed)

    def _connected(self, cwd: str):
        self.status_text.setText("Connected")
        sites.add_recent(self.site)
        sess = self.browser.session
        if sess is not None and sess.encrypted:
            what = "SFTP" if self.site.protocol == "sftp" else "FTP OVER TLS"
            self._lock_icon(True, f"Encrypted: {what}")
            self.enc_text.setText(what)
        else:
            self._lock_icon(False, "Not encrypted: plain FTP")
            self.enc_text.setText("FTP (NOT ENCRYPTED)")
        if self.site.local_dir and os.path.isdir(self.site.local_dir):
            self.local.go(self.site.local_dir)
        self.navigate(self.site.remote_dir or cwd)
        self._title()

    def _connect_failed(self, error: str):
        self.log("Error", error)
        self.status_text.setText("Could not connect")
        self._lock_icon(None, "")
        self.enc_text.setText("")
        self._title()

    def _lock_icon(self, encrypted, tip):
        if encrypted is None:
            self.lock.clear()
            return
        pm = QPixmap(36, 36)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        draw_icon(p, "lock", QRectF(0, 0, 18, 18), QColor(theme.LED_ORANGE if encrypted else theme.TEXT_DIM), 1.5)
        p.end()
        self.lock.setPixmap(pm)
        self.lock.setToolTip(tip)

    def disconnect(self):
        if self.queue is not None:
            self.queue.stop()
        self.browser.disconnect()
        self.remote.clear()
        self._lock_icon(None, "")
        self.enc_text.setText("")
        self.status_text.setText("Disconnected from server")
        self.log("Status", "Disconnected from server")
        self.site_connected = False
        self._title()

    def reconnect(self):
        if self.site is not None:
            self.connect_to(self.site, password_prompt=False)

    def cancel(self):
        if self.queue is not None:
            self.queue.stop()
            self.log("Status", "Queue stopped")

    def _title(self):
        if self.site is not None and self.browser.connected:
            who = f"{self.site.user}@" if self.site.user and self.site.user != "anonymous" else ""
            self.setWindowTitle(f"{self.site.name or who + self.site.host} - PR7-F")
        else:
            self.setWindowTitle("PR7-F")

    # -------------------------------------------------------------------------- browsing
    def navigate(self, path: str, done=None):
        if not path:
            return

        def listing(sess, path=path):
            return path, sess.list(path)

        def show(result):
            p, entries = result
            old = self.remote.path
            self.remote.show_listing(p, entries)
            if self.toolbar.keys["compare"].isChecked():
                compare(self.local.model, self.remote.model)
            if self.sync_base and old and old != p:
                self._sync_from_remote(p)
            if done:
                done()
        self.browser.run(listing, show, lambda e: self.log("Error", e))

    def refresh(self):
        self.local.refresh()
        if self.browser.connected and self.remote.path:
            self.navigate(self.remote.path)

    def _local_navigated(self, path):
        settings.set("local_dir", path)
        if self.toolbar.keys["compare"].isChecked():
            compare(self.local.model, self.remote.model)
        if self.sync_base and self.browser.connected:
            lbase, rbase = self.sync_base
            rel = os.path.relpath(path, lbase) if path.startswith(lbase) else None
            if rel is not None and not rel.startswith(".."):
                target = rbase if rel == "." else remote.join(rbase, rel.replace(os.sep, "/"))
                if target != self.remote.path:
                    self._syncing = True
                    self.navigate(target)

    def _sync_from_remote(self, path):
        if getattr(self, "_syncing", False):
            self._syncing = False
            return
        lbase, rbase = self.sync_base
        if path == rbase or path.startswith(rbase.rstrip("/") + "/"):
            rel = path[len(rbase):].strip("/")
            target = os.path.join(lbase, *rel.split("/")) if rel else lbase
            if os.path.isdir(target) and target != self.local.path:
                self.local.go(target)

    def toggle_sync(self):
        key = self.toolbar.keys["sync"]
        if self.sender() is not key:  # from a menu or a shortcut: flip the key, as clicking it does
            key.setChecked(not key.isChecked())
        if key.isChecked():
            if not (self.browser.connected and self.remote.path):
                self.toolbar.keys["sync"].setChecked(False)
                return
            self.sync_base = (self.local.path, self.remote.path)
            self.log("Status", f"Synchronised browsing: {self.local.path} with {self.remote.path}")
        else:
            self.sync_base = None

    def toggle_compare(self):
        key = self.toolbar.keys["compare"]
        if self.sender() is not key:
            key.setChecked(not key.isChecked())
        if key.isChecked():
            compare(self.local.model, self.remote.model)
        else:
            clear_compare(self.local.model, self.remote.model)

    def _toggle(self, key, widget):
        k = self.toolbar.keys[key]
        if self.sender() is not k:
            k.setChecked(not k.isChecked())
        widget.setVisible(k.isChecked())

    def toggle_log(self):
        self._toggle("log", self.logview)

    def toggle_local_tree(self):
        self._toggle("localtree", self.local.tree)

    def toggle_remote_tree(self):
        self._toggle("remotetree", self.remote.tree)

    # -------------------------------------------------------------------------- filters, search
    def _filtered_out(self, item) -> bool:
        """Folder transfers leave out what the source side's filters hide (FileZilla's default)."""
        if item.direction == "upload":
            return self.filters.hides("local", os.path.basename(item.local), item.size, item.mtime, item.is_dir,
                                      item.local)
        return self.filters.hides("remote", posixpath.basename(item.remote), item.size, item.mtime,
                                  item.is_dir, item.remote)

    def set_filters(self, fs):
        from . import filters
        self.filters = fs
        filters.save(fs)
        self.local.filters = self.remote.filters = fs
        self.local.refilter()
        self.remote.refilter()
        self._filter_key()

    def _filter_key(self):
        key = self.toolbar.keys["filter"]
        key.setCheckable(True)
        key.setChecked(bool(self.filters.local or self.filters.remote))  # lit while a filter is on, as FileZilla

    def open_filters(self):
        from .filter_dialog import FiltersDialog
        dlg = FiltersDialog(self.filters, self)
        self._dialog = dlg  # tests drive the open dialog
        if dlg.exec():
            self.set_filters(dlg.result())
        else:
            self._filter_key()

    def quick_search(self):
        """Ctrl+F: the quick search box of the list that has the focus (the local one otherwise)."""
        pane = self.remote if self.remote.isAncestorOf(QApplication.focusWidget() or self) else self.local
        pane.quick.open_search()

    def search_remote(self):
        from .filter_dialog import SearchDialog
        if not self.browser.connected:
            QMessageBox.information(self, "Search remote files", "Connect to a server first.")
            return
        dlg = SearchDialog(self)
        self._dialog = dlg
        dlg.show()

    def toggle_queue(self):
        self._toggle("queue", self.queue_tabs)

    # -------------------------------------------------------------------------- transfers
    def _queue(self) -> TransferQueue | None:
        if self.site is None or not self.browser.connected:
            QMessageBox.information(self, "PR7-F", "Connect to a server first.")
            return None
        if self.queue is None:
            site = self.site
            self.queue = TransferQueue(lambda: self.browser.open(site), workers=settings.get_int("transfers", 2),
                                       ask_exists=lambda ex: self.asker.ask("exists", ex), log=self._log_from_thread,
                                       exclude=self._filtered_out)
        return self.queue

    def _log_from_thread(self, kind, text):
        self.browser.logged.emit(kind, text)

    def upload(self, rows, start: bool = False, target_folder: str = ""):
        q = self._queue()
        if q is None or not rows:
            return
        base = remote.join(self.remote.path, target_folder) if target_folder else self.remote.path
        for r in rows:
            path = r if isinstance(r, str) else self.local.full(r.name)
            q.upload(path, remote.join(base, os.path.basename(path.rstrip("\\/"))))
        if start:
            q.start()

    def download(self, rows, start: bool = False, target_folder: str = ""):
        q = self._queue()
        if q is None or not rows:
            return
        base = os.path.join(self.local.path, target_folder) if target_folder else self.local.path
        for r in rows:
            e = self.remote.entry(r.name) or remote.Entry(r.name, r.size, r.mtime, r.is_dir)
            q.download(self.remote.full(r.name), os.path.join(base, r.name), e)
        if start:
            q.start()

    def _dropped_remote(self, source, items, folder):
        if source == "local":
            self.upload([self.local.full(n) for n in items], True, folder)
        elif source == "explorer":
            self.upload(items, True, folder)

    def _dropped_local(self, source, items, folder):
        if source == "remote":
            rows = [r for r in self.remote.model.rows if r.name in set(items)]
            self.download(rows, True, folder)

    def process_queue(self):
        if self.queue is not None:
            self.queue.start()

    def stop_queue(self):
        self.cancel()

    def retry_failed(self):
        if self.queue is not None:
            self.queue.retry_failed()
            self.queue.start()

    def clear_finished(self):
        if self.queue is not None:
            with self.queue.lock:
                self.queue.items = [i for i in self.queue.items if i.status not in ("done", "skipped")]

    def _tick(self):
        """5 times a second: the queue's tabs, the status bar, and listings refreshed after transfers into them."""
        q = self.queue
        if q is None:
            return
        snap = q.snapshot()
        for k, m in self.models.items():
            m.set_rows(snap[k])
        for i, (k, title) in enumerate((("queued", "QUEUED FILES"), ("failed", "FAILED TRANSFERS"),
                                        ("done", "SUCCESSFUL TRANSFERS"))):
            n = len(snap[k])
            self.queue_tabs.setTabText(i, f"{title} ({n})" if n else title)
        left = q.bytes_left()
        self.queue_text.setText(f"Queue: {left / 1048576:.1f} MB" if left else "Queue: empty")
        newly = [i for i in snap["done"] if i.id not in self._done_seen and i.status == "done"]
        for i in newly:
            self._done_seen.add(i.id)
        if any(i.direction == "upload" and remote.parent(i.remote) == self.remote.path for i in newly):
            self.navigate(self.remote.path)
        if any(i.direction == "download" and os.path.dirname(i.local) == self.local.path for i in newly):
            self.local.refresh()
        active = [i for i in snap["queued"] if i.status == "active"]
        if active:
            self.status_text.setText(f"{'Uploading' if active[0].direction == 'upload' else 'Downloading'} "
                                     f"{os.path.basename(active[0].local)}")
        elif snap["queued"] and not any(t.is_alive() for t in q.threads):
            self.status_text.setText("Queue stopped: Transfer > Process queue (Ctrl+P) to continue")
        elif not snap["queued"] and self.browser.connected:
            self.status_text.setText("Connected")

    def _queue_menu(self, kind, pos):
        if self.queue is None:
            return
        view = self.queue_views[kind]
        ids = [self.models[kind].rows[i.row()].id for i in view.selectionModel().selectedRows()]
        m = QMenu(self)
        m.addAction("Process queue", self.process_queue)
        if kind == "failed":
            m.addAction("Retry failed transfers", self.retry_failed)
        m.addAction("Remove selected", lambda: self.queue.cancel(ids)).setEnabled(bool(ids))
        m.addAction("Clear finished transfers", self.clear_finished)
        m.exec(view.viewport().mapToGlobal(pos))

    # -------------------------------------------------------------------------- local menu
    def _local_menu(self, pos):
        rows = self.local.selected()
        m = QMenu(self)
        m.addAction("Upload", lambda: self.upload(rows, True)).setEnabled(bool(rows) and self.browser.connected)
        m.addAction("Add files to queue", lambda: self.upload(rows)).setEnabled(bool(rows) and self.browser.connected)
        m.addSeparator()
        m.addAction("Open", lambda: [QDesktopServices.openUrl(QUrl.fromLocalFile(self.local.full(r.name)))
                                     for r in rows]).setEnabled(bool(rows))
        m.addAction("Create directory", self.local_mkdir)
        m.addAction("Refresh", self.local.refresh)
        m.addSeparator()
        m.addAction("Delete", lambda: self.local_delete(rows)).setEnabled(bool(rows))
        m.addAction("Rename", lambda: self.local_rename(rows[0])).setEnabled(len(rows) == 1)
        m.exec(self.local.list.viewport().mapToGlobal(pos))

    def local_mkdir(self, name: str | None = None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Create directory", "Please enter the name of the directory:",
                                            text="New directory")
            if not ok or not name.strip():
                return
        try:
            os.makedirs(self.local.full(name.strip()))
        except OSError as e:
            QMessageBox.warning(self, "Create directory", e.strerror or str(e))
        self.local.refresh()

    def local_delete(self, rows, confirm: bool = True):
        if confirm and QMessageBox.question(self, "Confirmation needed",
                                            f"Really delete {len(rows)} item(s) from your computer?",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            recycle([self.local.full(r.name) for r in rows])
        except OSError as e:
            QMessageBox.warning(self, "Delete", str(e))
        self.local.refresh()

    def local_rename(self, row, new: str | None = None):
        if new is None:
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=row.name)
            if not ok or not new.strip() or new == row.name:
                return
        try:
            os.rename(self.local.full(row.name), self.local.full(new.strip()))
        except OSError as e:
            QMessageBox.warning(self, "Rename", e.strerror or str(e))
        self.local.refresh()

    # -------------------------------------------------------------------------- remote menu
    def _remote_menu(self, pos):
        rows = self.remote.selected()
        on = self.browser.connected
        m = QMenu(self)
        m.addAction("Download", lambda: self.download(rows, True)).setEnabled(bool(rows) and on)
        m.addAction("Add files to queue", lambda: self.download(rows)).setEnabled(bool(rows) and on)
        m.addAction("View/Edit", lambda: self.view_edit(rows[0])).setEnabled(
            len(rows) == 1 and not rows[0].is_dir and on)
        m.addSeparator()
        m.addAction("Create directory", self.remote_mkdir).setEnabled(on)
        m.addAction("Refresh", lambda: self.navigate(self.remote.path)).setEnabled(on)
        m.addSeparator()
        m.addAction("Delete", lambda: self.remote_delete(rows)).setEnabled(bool(rows) and on)
        m.addAction("Rename", lambda: self.remote_rename(rows[0])).setEnabled(len(rows) == 1 and on)
        m.addAction("Copy URL(s) to clipboard", lambda: self.copy_urls(rows)).setEnabled(bool(rows) and on)
        m.addAction("File permissions...", lambda: self.remote_chmod(rows)).setEnabled(bool(rows) and on)
        m.exec(self.remote.list.viewport().mapToGlobal(pos))

    def _remote_job(self, fn, then_refresh=True):
        self.browser.run(fn, (lambda _r: self.navigate(self.remote.path)) if then_refresh else None,
                         lambda e: (self.log("Error", e), self.navigate(self.remote.path)))

    def remote_mkdir(self, name: str | None = None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Create directory", "Please enter the name of the directory:",
                                            text="New directory")
            if not ok or not name.strip():
                return
        path = self.remote.full(name.strip())
        self._remote_job(lambda s: s.mkdir(path))

    def remote_delete(self, rows, confirm: bool = True):
        if confirm and QMessageBox.question(self, "Confirmation needed",
                                            f"Really delete {len(rows)} item(s) from the server?",
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        targets = [(self.remote.full(r.name), r.is_dir and not r.is_link) for r in rows]

        def delete_all(sess):
            def rm(path, is_dir):
                if is_dir:
                    for e in sess.list(path):
                        rm(remote.join(path, e.name), e.is_dir and not e.is_link)
                    sess.rmdir(path)
                else:
                    sess.delete(path)
            for path, is_dir in targets:
                rm(path, is_dir)
        self._remote_job(delete_all)

    def remote_rename(self, row, new: str | None = None):
        if new is None:
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=row.name)
            if not ok or not new.strip() or new == row.name:
                return
        old, target = self.remote.full(row.name), self.remote.full(new.strip())
        self._remote_job(lambda s: s.rename(old, target))

    def remote_chmod(self, rows, mode: int | None = None):
        if mode is None:
            from .dialogs import ChmodDialog
            e = self.remote.entry(rows[0].name)
            dlg = ChmodDialog([r.name for r in rows], e.mode if e else None, self)
            if not dlg.exec():
                return
            mode = dlg.mode()
        paths = [self.remote.full(r.name) for r in rows]
        self._remote_job(lambda s: [s.chmod(p, mode) for p in paths])

    def copy_urls(self, rows):
        s = self.site
        scheme = "sftp" if s.protocol == "sftp" else "ftp"
        port = f":{s.port}" if s.port and s.port != s.real_port or (s.port and s.port not in (21, 22)) else ""
        who = f"{s.user}@" if s.user and s.user != "anonymous" else ""
        from urllib.parse import quote
        QApplication.clipboard().setText("\n".join(f"{scheme}://{who}{s.host}{port}{quote(self.remote.full(r.name))}"
                                                   for r in rows))

    # -------------------------------------------------------------------------- View/Edit
    def view_edit(self, row):
        """Download to a temporary copy, open it with its program; when it's saved, offer to upload it back."""
        folder = tempfile.mkdtemp(prefix="pr7f-edit-")
        local = os.path.join(folder, row.name)
        rpath = self.remote.full(row.name)
        site = self.site

        def fetch(_sess):
            s = self.browser.open(site)
            try:
                s.download(rpath, local)
            finally:
                s.close()
            return local

        def opened(path):
            self.edited[path] = rpath
            self.watcher.addPath(path)
            if not self.answers.get("no_open"):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.browser.run(fetch, opened, lambda e: self.log("Error", e))

    def _edited_changed(self, path):
        rpath = self.edited.get(path)
        if not rpath or not os.path.exists(path):
            return
        if path not in self.watcher.files():
            self.watcher.addPath(path)  # editors that save by replacing the file
        ask = self.answers.get("upload_edited")
        ok = ask(path) if ask else QMessageBox.question(
            self, "File has changed", f"{os.path.basename(path)} has changed. Upload it back to the server?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok and self.queue is not None or ok and self._queue() is not None:
            q = self.queue
            q.default_action["upload"] = None
            it = q.upload(path, rpath)
            old = q.ask_exists
            q.ask_exists = lambda ex: ("overwrite", False) if ex.item is it else old(ex)
            q.start()

    # -------------------------------------------------------------------------- sites, settings
    def site_manager(self):
        from .site_manager import SiteManager
        dlg = SiteManager(self)
        self._dialog = dlg
        if dlg.exec() and dlg.chosen is not None:
            self.connect_to(dlg.chosen)

    def save_current(self):
        if self.site is None:
            return
        all_sites = sites.load_sites()
        d = sites.new_site(self.site.host)
        for k in sites.SITE_KEYS:
            if hasattr(self.site, k) and k not in ("name",):
                d[k] = getattr(self.site, k)
        all_sites.append(d)
        sites.save_sites(all_sites)
        sites.set_password(d["id"], self.site.password)
        self.log("Status", f'"{d["name"]}" added to the Site Manager')

    def open_settings(self):
        from .dialogs import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            dlg.apply()
            if self.queue is not None:
                self.queue.workers = settings.get_int("transfers", 2)
            theme.set_finish(settings.get("finish", "obsidian"))
            app = QApplication.instance()
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
            self.header.update()

    def about(self):
        QMessageBox.about(self, "About PR7-F", f"<b>Paragon PR7-F</b> {__version__}<br>File transfer that works the "
                          "way FileZilla works.<br><br>SFTP: paramiko (LGPL-2.1). Passwords: Windows Credential "
                          "Manager via keyring (MIT).")

    def closeEvent(self, e):
        if self.queue is not None:
            self.queue.stop()
        self.browser.disconnect()
        self.browser.stop()
        super().closeEvent(e)
