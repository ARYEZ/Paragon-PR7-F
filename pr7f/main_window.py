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
                               QSplitter, QStackedWidget, QStatusBar, QStyledItemDelegate, QTabBar, QTabWidget,
                               QToolButton, QTreeView,
                               QVBoxLayout, QWidget)

from . import __version__, remote, settings, sites, theme
from .browser import Asker, Browser
from .panes import LocalPane, RemotePane, clear_compare, compare
from .transfers import TransferQueue
from .widgets import Header, Toolbar, draw_icon

LOG_COLOURS = {"Status": "TEXT_DIM", "Command": "TEXT", "Response": "LED_ORANGE", "Error": "METER_RED"}
QUEUE_COLUMNS = ["Server", "Local file", "Direction", "Remote file", "Size", "Status"]


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
        self.servers: dict[int, str] = {}  # item id -> the tab's server name (one queue list for every tab)

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
                return self.servers.get(it.id, "")
            if c == 1:
                return it.local
            if c == 2:
                return "→" if it.direction == "upload" else "←"
            if c == 3:
                return it.remote
            if c == 4:
                return "" if it.is_dir else f"{it.size:,}"
            if c == 5:
                return {"queued": "", "active": "Transferring", "done": "Done", "skipped": "Skipped",
                        "failed": it.error}.get(it.status, it.status)
        if role == Qt.TextAlignmentRole and c == 4:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and c == 5 and it.status == "failed":
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
    for i, w in enumerate([200, 400, 90, 380, 110]):
        v.header().resizeSection(i, w)
    v.header().setStretchLastSection(True)
    v.header().setSectionResizeMode(QHeaderView.Interactive)
    v.setItemDelegateForColumn(5, ProgressDelegate(v))
    return v


# Menus: (text with shortcut after a tab, slot) ; "-" separator; slot None: not yet (greyed out).
MENUS = {
    "&File": [("&Site Manager...\tCtrl+S", "site_manager"), ("&Copy current connection to Site Manager...",
                                                              "save_current"), "-", ("New &tab\tCtrl+T", "new_tab"),
              ("&Close tab\tCtrl+W", "close_tab"), "-", ("E&xit\tCtrl+Q", "close")],
    "&Edit": [("&Settings...", "open_settings")],
    "&View": [("&Refresh\tF5", "refresh"), ("Directory &listing filters...\tCtrl+I", "open_filters"),
              ("&Quick search\tCtrl+F", "quick_search"), ("Directory &comparison", "toggle_compare"), "-",
              ("&Message log", "toggle_log"), ("&Local directory tree", "toggle_local_tree"),
              ("&Remote directory tree", "toggle_remote_tree"), ("Transfer &queue", "toggle_queue")],
    "&Transfer": [("&Process queue\tCtrl+P", "process_queue"), ("&Stop processing", "stop_queue"),
                  ("&Retry failed transfers", "retry_failed"), ("&Clear finished transfers", "clear_finished")],
    "S&erver": [("&Cancel current operation\tCtrl+.", "cancel"), "-", ("&Reconnect\tCtrl+R", "reconnect"),
                ("&Disconnect\tCtrl+D", "disconnect"), "-", ("&Search remote files...\tF3", "search_remote")],
    "&Bookmarks": [("&Add bookmark...\tCtrl+B", "add_bookmark"),
                   ("&Manage bookmarks...\tCtrl+Shift+B", "manage_bookmarks")],
    "&Help": [("&About PR7-F...", "about")],
}
TOOLBAR = {"sitemanager": "site_manager", "log": "toggle_log", "localtree": "toggle_local_tree",
           "remotetree": "toggle_remote_tree", "queue": "toggle_queue", "refresh": "refresh",
           "process": "process_queue", "cancel": "cancel", "disconnect": "disconnect", "reconnect": "reconnect",
           "compare": "toggle_compare", "sync": "toggle_sync", "filter": "open_filters", "search": "search_remote"}


class Tab:
    """One connection tab, as FileZilla's: its own site, connection, local and remote panes, message log,
    transfer queue, synchronised browsing and comparison. The window shows the current one."""

    def __init__(self, window: "MainWindow", start_local: str):
        self.window = window
        self.site: remote.Site | None = None
        self.queue: TransferQueue | None = None
        self.sync_base: tuple[str, str] | None = None
        self.syncing = False
        self.compare = False
        self.edited: dict[str, str] = {}   # View/Edit: local temp copy -> remote path
        self.enc: tuple = (None, "", "")   # encrypted?, tooltip, status-bar text
        self.status = ""
        self.browser = Browser(window.asker)
        self.page = QSplitter(Qt.Vertical)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(5000)
        self.page.addWidget(self.logview)
        sites_split = QSplitter(Qt.Horizontal)
        self.local = LocalPane()
        self.remote = RemotePane()
        sites_split.addWidget(self.local)
        sites_split.addWidget(self.remote)
        self.page.addWidget(sites_split)
        self.page.setSizes([170, 560])
        w = window
        self.browser.logged.connect(self.log)
        self.local.on_open_file = lambda rows: w.upload(rows, start=True)
        self.local.list.dropped.connect(w._dropped_local)
        self.local.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.local.list.customContextMenuRequested.connect(w._local_menu)
        self.local.navigated.connect(lambda path: w._local_navigated(path, self))
        self.remote.on_open_file = lambda rows: w.download(rows, start=True)
        self.remote.navigate_requested.connect(lambda path: w.navigate(path, tab=self))
        self.remote.list.dropped.connect(w._dropped_remote)
        self.remote.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.remote.list.customContextMenuRequested.connect(w._remote_menu)
        self.local.filters = self.remote.filters = w.filters
        self.local.refilter()
        self.remote.refilter()
        self.logview.setVisible(w.toolbar.keys["log"].isChecked())
        self.local.tree.setVisible(w.toolbar.keys["localtree"].isChecked())
        self.remote.tree.setVisible(w.toolbar.keys["remotetree"].isChecked())
        self.local.go(start_local)

    def log(self, kind: str, text: str):
        f = QTextCharFormat()
        f.setForeground(QColor(getattr(theme, LOG_COLOURS.get(kind, "TEXT"))))
        cur = self.logview.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(f"{kind + ':':<10}{text}\n", f)
        self.logview.setTextCursor(cur)
        self.logview.ensureCursorVisible()

    @property
    def connected(self) -> bool:
        return self.browser.connected

    @property
    def label(self) -> str:
        """The tab's name: the site's, or user@host, as FileZilla's tabs."""
        s = self.site
        if s is None or not self.connected:
            return "Not connected"
        who = f"{s.user}@" if s.user and s.user != "anonymous" else ""
        return s.name or who + s.host

    def close(self):
        if self.queue is not None:
            self.queue.stop()
        self.browser.disconnect()
        self.browser.stop()


class MainWindow(QMainWindow):
    def __init__(self, start_local: str | None = None):
        super().__init__()
        self.resize(1560, 1000)
        self.answers: dict = {}  # kind -> function(payload): replaces a dialog (tests)
        self.asker = Asker({"hostkey": lambda p: self._ask("hostkey", p), "cert": lambda p: self._ask("cert", p),
                            "exists": lambda p: self._ask("exists", p)})
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._edited_changed)
        self.tabs: list[Tab] = []
        self._build()
        self.new_tab(start_local or settings.get("local_dir", "") or os.path.expanduser("~"))
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
            if title == "&Bookmarks":
                self.bookmarks_menu = m
                m.aboutToShow.connect(self._fill_bookmarks)
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
        from . import filters
        self.filters = filters.load()
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.tabbar = QTabBar()
        self.tabbar.setTabsClosable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.currentChanged.connect(self._tab_changed)
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        tl.addWidget(self.tabbar)
        self.stack = QStackedWidget()
        tl.addWidget(self.stack, 1)
        self.main.addWidget(top)
        self.queue_tabs = QTabWidget()
        self.models = {k: QueueModel() for k in ("queued", "failed", "done")}
        self.queue_views = {k: _queue_view(m) for k, m in self.models.items()}
        for k, title in (("queued", "QUEUED FILES"), ("failed", "FAILED TRANSFERS"), ("done", "SUCCESSFUL TRANSFERS")):
            self.queue_tabs.addTab(self.queue_views[k], title)
            v = self.queue_views[k]
            v.setContextMenuPolicy(Qt.CustomContextMenu)
            v.customContextMenuRequested.connect(lambda pos, kind=k: self._queue_menu(kind, pos))
        self.main.addWidget(self.queue_tabs)
        self.main.setSizes([760, 200])
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

    # -------------------------------------------------------------------------- tabs
    # What the rest of the window (and the tests) call window.site, window.local ... is the current tab's.
    @property
    def tab(self) -> Tab:
        i = self.tabbar.currentIndex()
        return self.tabs[i if 0 <= i < len(self.tabs) else 0]

    site = property(lambda self: self.tab.site, lambda self, v: setattr(self.tab, "site", v))
    queue = property(lambda self: self.tab.queue, lambda self, v: setattr(self.tab, "queue", v))
    sync_base = property(lambda self: self.tab.sync_base, lambda self, v: setattr(self.tab, "sync_base", v))
    browser = property(lambda self: self.tab.browser)
    local = property(lambda self: self.tab.local)
    remote = property(lambda self: self.tab.remote)
    logview = property(lambda self: self.tab.logview)
    edited = property(lambda self: self.tab.edited)

    def new_tab(self, local: str | None = None) -> Tab:
        """File > New tab (Ctrl+T): an unconnected tab, at the current tab's local folder."""
        start = local or (self.tab.local.path if self.tabs else os.path.expanduser("~"))
        tab = Tab(self, start)
        self.tabs.append(tab)
        self.stack.addWidget(tab.page)
        self.tabbar.addTab(tab.label)
        self.tabbar.setCurrentIndex(len(self.tabs) - 1)
        return tab

    def close_tab(self, index: int | None = None):
        """File > Close tab (Ctrl+W) or the tab's ×. The last tab stays: closing it only disconnects."""
        i = self.tabbar.currentIndex() if index is None or index is False else index
        tab = self.tabs[i]
        busy = tab.queue is not None and tab.queue.snapshot()["queued"]
        if busy:
            ask = self.answers.get("close_busy_tab")
            ok = ask(tab) if ask else QMessageBox.question(
                self, "Close tab", f"{tab.label} still has files in the queue. Close the tab and drop them?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
            if not ok:
                return
        if len(self.tabs) == 1:
            self.disconnect()
            return
        tab.close()
        self.tabs.pop(i)
        self.tabbar.removeTab(i)  # (the bar moves to a neighbour first; _tab_changed shows it)
        self.stack.removeWidget(tab.page)
        tab.page.deleteLater()
        self._tab_changed(self.tabbar.currentIndex())

    def _tab_changed(self, index: int):
        if not (0 <= index < len(self.tabs)):
            return
        tab = self.tabs[index]
        self.stack.setCurrentWidget(tab.page)
        self.toolbar.keys["sync"].setChecked(tab.sync_base is not None)
        self.toolbar.keys["compare"].setChecked(tab.compare)
        encrypted, tip, text = tab.enc
        self._lock_icon(encrypted, tip)
        self.enc_text.setText(text)
        self.status_text.setText(tab.status)
        self._title()

    def _relabel(self, tab: Tab):
        if tab in self.tabs:
            self.tabbar.setTabText(self.tabs.index(tab), tab.label)
            self.tabbar.setTabToolTip(self.tabs.index(tab), tab.site.host if tab.site else "")
        if tab is self.tab:
            self._title()

    def _set_status(self, tab: Tab, text: str):
        tab.status = text
        if tab is self.tab:
            self.status_text.setText(text)

    def _set_enc(self, tab: Tab, enc: tuple):
        tab.enc = enc
        if tab is self.tab:
            self._lock_icon(enc[0], enc[1])
            self.enc_text.setText(enc[2])

    # -------------------------------------------------------------------------- the log, questions
    def log(self, kind: str, text: str):
        self.tab.log(kind, text)

    def _ask(self, kind: str, payload):
        if kind in self.answers:
            return self.answers[kind](payload)
        from .dialogs import AlreadyConnectedDialog, CertDialog, FileExistsDialog, HostKeyDialog
        if kind == "already":
            dlg = AlreadyConnectedDialog(*payload, self)
        else:
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

    def connect_to(self, site: remote.Site, password_prompt: bool = True, tab: Tab | None = None):
        """Connect, as FileZilla: when this tab is already connected, ask whether to use a new tab or to abort
        the previous connection (or do what "Always perform this action" remembered)."""
        if password_prompt and site.logon == "ask" or (site.logon == "normal" and not site.password and site.user
                                                       and site.protocol == "sftp" and password_prompt):
            pw, ok = QInputDialog.getText(self, "Enter password", f"Password for {site.user}@{site.host}:",
                                          QLineEdit.Password)
            if not ok:
                return
            site.password = pw
        if tab is None:
            tab = self.tab
            if tab.connected:
                choice = settings.get("already_connected", "ask")
                if choice not in ("new_tab", "replace"):
                    choice = self._ask("already", (tab.label, site.name or site.host))
                if choice is None:
                    return
                if choice == "new_tab":
                    tab = self.new_tab()
        if tab.queue is not None:
            tab.queue.stop()
        tab.remote.clear()
        clear_compare(tab.local.model, tab.remote.model)
        tab.site = site
        tab.queue = None
        tab.sync_base = None
        self._set_status(tab, f"Connecting to {site.host}...")
        tab.browser.connect(site, lambda cwd: self._connected(cwd, tab), lambda e: self._connect_failed(e, tab))
        return tab

    def _connected(self, cwd: str, tab: Tab | None = None):
        tab = tab or self.tab
        self._set_status(tab, "Connected")
        sites.add_recent(tab.site)
        sess = tab.browser.session
        if sess is not None and sess.encrypted:
            what = "SFTP" if tab.site.protocol == "sftp" else "FTP OVER TLS"
            self._set_enc(tab, (True, f"Encrypted: {what}", what))
        else:
            self._set_enc(tab, (False, "Not encrypted: plain FTP", "FTP (NOT ENCRYPTED)"))
        if tab.site.local_dir and os.path.isdir(tab.site.local_dir):
            tab.local.go(tab.site.local_dir)
        self.navigate(tab.site.remote_dir or cwd, tab=tab)
        self._relabel(tab)

    def _connect_failed(self, error: str, tab: Tab | None = None):
        tab = tab or self.tab
        tab.log("Error", error)
        self._set_status(tab, "Could not connect")
        self._set_enc(tab, (None, "", ""))
        self._relabel(tab)

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
        tab = self.tab
        if tab.queue is not None:
            tab.queue.stop()
        tab.browser.disconnect()
        tab.remote.clear()
        tab.sync_base = None
        self.toolbar.keys["sync"].setChecked(False)
        self._set_enc(tab, (None, "", ""))
        self._set_status(tab, "Disconnected from server")
        tab.log("Status", "Disconnected from server")
        tab.browser.run(lambda _s: None, lambda _r: self._relabel(tab), lambda _e: self._relabel(tab))

    def reconnect(self):
        if self.site is not None:
            self.connect_to(self.site, password_prompt=False, tab=self.tab)

    def cancel(self):
        if self.queue is not None:
            self.queue.stop()
            self.log("Status", "Queue stopped")

    def _title(self):
        tab = self.tab
        self.setWindowTitle(f"{tab.label} - PR7-F" if tab.site is not None and tab.connected else "PR7-F")

    # -------------------------------------------------------------------------- browsing
    def navigate(self, path: str, done=None, tab: Tab | None = None):
        if not path:
            return
        tab = tab or self.tab

        def listing(sess, path=path):
            return path, sess.list(path)

        def show(result):
            p, entries = result
            old = tab.remote.path
            tab.remote.show_listing(p, entries)
            if tab.compare:
                compare(tab.local.model, tab.remote.model)
            if tab.sync_base and old and old != p:
                self._sync_from_remote(p, tab)
            if done:
                done()
        tab.browser.run(listing, show, lambda e: tab.log("Error", e))

    def refresh(self):
        self.local.refresh()
        if self.browser.connected and self.remote.path:
            self.navigate(self.remote.path)

    def _local_navigated(self, path, tab: Tab | None = None):
        tab = tab or self.tab
        settings.set("local_dir", path)
        if tab.compare:
            compare(tab.local.model, tab.remote.model)
        if tab.sync_base and tab.connected:
            lbase, rbase = tab.sync_base
            rel = os.path.relpath(path, lbase) if path.startswith(lbase) else None
            if rel is not None and not rel.startswith(".."):
                target = rbase if rel == "." else remote.join(rbase, rel.replace(os.sep, "/"))
                if target != tab.remote.path:
                    tab.syncing = True
                    self.navigate(target, tab=tab)

    def _sync_from_remote(self, path, tab: Tab | None = None):
        tab = tab or self.tab
        if tab.syncing:
            tab.syncing = False
            return
        lbase, rbase = tab.sync_base
        if path == rbase or path.startswith(rbase.rstrip("/") + "/"):
            rel = path[len(rbase):].strip("/")
            target = os.path.join(lbase, *rel.split("/")) if rel else lbase
            if os.path.isdir(target) and target != tab.local.path:
                tab.local.go(target)

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
        self.tab.compare = key.isChecked()
        if key.isChecked():
            compare(self.local.model, self.remote.model)
        else:
            clear_compare(self.local.model, self.remote.model)

    def _toggle(self, key, part):
        """The log, the trees: shown or hidden in every tab, as the toolbar key says."""
        k = self.toolbar.keys[key]
        if self.sender() is not k:
            k.setChecked(not k.isChecked())
        for tab in self.tabs:
            part(tab).setVisible(k.isChecked())

    def toggle_log(self):
        self._toggle("log", lambda t: t.logview)

    def toggle_local_tree(self):
        self._toggle("localtree", lambda t: t.local.tree)

    def toggle_remote_tree(self):
        self._toggle("remotetree", lambda t: t.remote.tree)

    # -------------------------------------------------------------------------- bookmarks
    @property
    def site_id(self) -> str:
        return self.site.id if self.site is not None and self.browser.connected else ""

    def bookmark_list(self) -> list[tuple[str, object]]:
        """What the Bookmarks menu lists after Add / Manage: global ones, then the connected site's."""
        from . import bookmarks
        items = [("global", b) for b in bookmarks.load_global()]
        if self.site_id:
            items += [("site", b) for b in bookmarks.load_site(self.site_id)]
        return items

    def _fill_bookmarks(self):
        m = self.bookmarks_menu
        for a in m.actions()[2:]:
            m.removeAction(a)
        items = self.bookmark_list()
        kinds = [k for k, _ in items]
        for i, (kind, b) in enumerate(items):
            if i == 0 or (kind == "site" and kinds[i - 1] == "global"):
                m.addSeparator()
            m.addAction(b.name.replace("&", "&&"), lambda b=b: self.go_bookmark(b))  # "&" isn't a shortcut here

    def add_bookmark(self):
        from .bookmark_dialog import AddBookmarkDialog
        dlg = AddBookmarkDialog(self.local.path, self.remote.path if self.browser.connected else "", self.site_id,
                                self)
        self._dialog = dlg
        dlg.exec()

    def manage_bookmarks(self):
        from .bookmark_dialog import ManageBookmarksDialog
        dlg = ManageBookmarksDialog(self.site_id, self)
        self._dialog = dlg
        dlg.exec()

    def go_bookmark(self, b):
        """Open a bookmark: its local folder, its remote folder (when connected), then synchronised browsing and
        comparison as it says. Synchronised browsing starts once both sides are there."""
        self.sync_base = None
        self.toolbar.keys["sync"].setChecked(False)
        if b.local and not self.local.go(b.local):
            self.log("Error", f"Bookmark {b.name}: the local directory {b.local} isn't there")
        key = self.toolbar.keys["compare"]
        if key.isChecked() != b.compare:
            key.setChecked(b.compare)
            (compare if b.compare else clear_compare)(self.local.model, self.remote.model)

        tab = self.tab
        tab.compare = b.compare

        def remote_done():
            if b.sync and b.local and tab.remote.path == b.remote:
                tab.sync_base = (tab.local.path, tab.remote.path)
                if tab is self.tab:
                    self.toolbar.keys["sync"].setChecked(True)
                tab.log("Status", f"Synchronised browsing: {tab.local.path} with {tab.remote.path}")
        if b.remote:
            if self.browser.connected:
                self.navigate(b.remote, done=remote_done, tab=tab)
            else:
                self.log("Status", f"Bookmark {b.name}: connect to a server to open {b.remote}")

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
        for tab in self.tabs:
            tab.local.filters = tab.remote.filters = fs
            tab.local.refilter()
            tab.remote.refilter()
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
        k = self.toolbar.keys["queue"]
        if self.sender() is not k:
            k.setChecked(not k.isChecked())
        self.queue_tabs.setVisible(k.isChecked())

    # -------------------------------------------------------------------------- transfers
    def _queue(self, tab: Tab | None = None) -> TransferQueue | None:
        tab = tab or self.tab
        if tab.site is None or not tab.connected:
            QMessageBox.information(self, "PR7-F", "Connect to a server first.")
            return None
        if tab.queue is None:
            site, browser = tab.site, tab.browser
            tab.queue = TransferQueue(lambda: browser.open(site), workers=settings.get_int("transfers", 2),
                                      ask_exists=lambda ex: self.asker.ask("exists", ex),
                                      log=lambda kind, text: browser.logged.emit(kind, text),
                                      exclude=self._filtered_out)
        return tab.queue

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

    def _queues(self) -> list[TransferQueue]:
        return [t.queue for t in self.tabs if t.queue is not None]

    def process_queue(self):
        """Transfer > Process queue: every tab's (one queue list, as FileZilla)."""
        for q in self._queues():
            q.start()

    def stop_queue(self):
        self.cancel()

    def retry_failed(self):
        for q in self._queues():
            q.retry_failed()
            q.start()

    def clear_finished(self):
        for q in self._queues():
            with q.lock:
                q.items = [i for i in q.items if i.status not in ("done", "skipped")]

    def _tick(self):
        """5 times a second: one queue list for every tab (with the server of each), the status bar, and listings
        refreshed after transfers into the folder a tab shows."""
        lists = {"queued": [], "failed": [], "done": []}
        servers: dict[int, str] = {}
        left = 0
        for tab in self.tabs:
            q = tab.queue
            if q is None:
                continue
            snap = q.snapshot()
            name = tab.site.name or tab.site.host if tab.site is not None else tab.label
            for k in lists:
                lists[k] += snap[k]
                for it in snap[k]:
                    servers[it.id] = name
            left += q.bytes_left()
            newly = [i for i in snap["done"] if i.id not in self._done_seen and i.status == "done"]
            for i in newly:
                self._done_seen.add(i.id)
            if any(i.direction == "upload" and remote.parent(i.remote) == tab.remote.path for i in newly):
                self.navigate(tab.remote.path, tab=tab)
            if any(i.direction == "download" and os.path.dirname(i.local) == tab.local.path for i in newly):
                tab.local.refresh()
            active = [i for i in snap["queued"] if i.status == "active"]
            if active:
                self._set_status(tab, f"{'Uploading' if active[0].direction == 'upload' else 'Downloading'} "
                                      f"{os.path.basename(active[0].local)}")
            elif snap["queued"] and not any(t.is_alive() for t in q.threads):
                self._set_status(tab, "Queue stopped: Transfer > Process queue (Ctrl+P) to continue")
            elif not snap["queued"] and tab.connected and tab.status.startswith(("Uploading", "Downloading",
                                                                                 "Queue stopped")):
                self._set_status(tab, "Connected")
        for k, m in self.models.items():
            m.servers = servers
            m.set_rows(lists[k])
        for i, (k, title) in enumerate((("queued", "QUEUED FILES"), ("failed", "FAILED TRANSFERS"),
                                        ("done", "SUCCESSFUL TRANSFERS"))):
            n = len(lists[k])
            self.queue_tabs.setTabText(i, f"{title} ({n})" if n else title)
        self.queue_text.setText(f"Queue: {left / 1048576:.1f} MB" if left else "Queue: empty")

    def _queue_menu(self, kind, pos):
        if not self._queues():
            return
        view = self.queue_views[kind]
        ids = [self.models[kind].rows[i.row()].id for i in view.selectionModel().selectedRows()]
        m = QMenu(self)
        m.addAction("Process queue", self.process_queue)
        if kind == "failed":
            m.addAction("Retry failed transfers", self.retry_failed)
        m.addAction("Remove selected", lambda: [q.cancel(ids) for q in self._queues()]).setEnabled(bool(ids))
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
        tab = self.tab
        tab.browser.run(fn, (lambda _r: self.navigate(tab.remote.path, tab=tab)) if then_refresh else None,
                        lambda e: (tab.log("Error", e), self.navigate(tab.remote.path, tab=tab)))

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
        tab = self.tab
        folder = tempfile.mkdtemp(prefix="pr7f-edit-")
        local = os.path.join(folder, row.name)
        rpath = tab.remote.full(row.name)
        site, browser = tab.site, tab.browser

        def fetch(_sess):
            s = browser.open(site)
            try:
                s.download(rpath, local)
            finally:
                s.close()
            return local

        def opened(path):
            tab.edited[path] = rpath
            self.watcher.addPath(path)
            if not self.answers.get("no_open"):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        browser.run(fetch, opened, lambda e: tab.log("Error", e))

    def _edited_changed(self, path):
        tab = next((t for t in self.tabs if path in t.edited), None)
        if tab is None or not os.path.exists(path):
            return
        rpath = tab.edited[path]
        if path not in self.watcher.files():
            self.watcher.addPath(path)  # editors that save by replacing the file
        ask = self.answers.get("upload_edited")
        ok = ask(path) if ask else QMessageBox.question(
            self, "File has changed", f"{os.path.basename(path)} has changed. Upload it back to {tab.label}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        q = self._queue(tab) if ok else None
        if q is not None:
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
            if hasattr(self.site, k) and k not in ("name", "id"):
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
            for q in self._queues():
                q.workers = settings.get_int("transfers", 2)
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
        for tab in self.tabs:
            tab.close()
        super().closeEvent(e)
