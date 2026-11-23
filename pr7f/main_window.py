"""The window, laid out like FileZilla's: quick-connect bar, message log, local and remote sites side by side
(folder tree over file list), the transfer queue at the bottom. (Mock-up: sample data, nothing connects.)"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QPlainTextEdit, QPushButton, QSplitter, QStatusBar, QStyledItemDelegate,
                               QTabWidget, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .widgets import Header, Toolbar, draw_icon, file_icon

MENUS = {
    "&File": ["&Site Manager...\tCtrl+S", "&Copy current connection to Site Manager...", "-",
              "New &tab\tCtrl+T", "&Close tab\tCtrl+W", "-", "&Export...", "&Import...", "-", "E&xit\tCtrl+Q"],
    "&Edit": ["&Network configuration wizard...", "&Clear private data...", "-", "&Settings..."],
    "&View": ["&Refresh\tF5", "Directory &listing filters...\tCtrl+I", "&Directory comparison", "-",
              "&Message log", "&Local directory tree", "&Remote directory tree", "Transfer &queue"],
    "&Transfer": ["&Process queue\tCtrl+P", "-", "&Default file exists action...", "Transfer &type", "-",
                  "&Manual transfer..."],
    "S&erver": ["&Cancel current operation\tCtrl+.", "-", "&Reconnect\tCtrl+R", "&Disconnect\tCtrl+D", "-",
                "&Search remote files...\tF3", "Enter &custom command...", "Force &showing hidden files"],
    "&Bookmarks": ["&Add bookmark...\tCtrl+B", "&Manage bookmarks...\tCtrl+Shift+B"],
    "&Help": ["&About PR7-F..."],
}

LOCAL_FILES = [("..", "", "", "", "up"), ("Artwork", "", "File folder", "2026-11-20 18:04", "folder"),
               ("Stems", "", "File folder", "2026-11-19 22:41", "folder"),
               ("01 Portal.flac", "31,224,118", "FLAC File", "2026-11-20 17:58", "file"),
               ("02 Ruins of Elsewhere.flac", "44,903,551", "FLAC File", "2026-11-20 17:58", "file"),
               ("03 Static Bloom.mp3", "10,842,212", "MP3 File", "2026-11-20 17:59", "file"),
               ("04 Signal Lost.mp3", "9,540,100", "MP3 File", "2026-11-20 17:59", "file"),
               ("05 Arc Light.mp3", "15,203,480", "MP3 File", "2026-11-20 17:59", "file"),
               ("ELSEWORLD.m3u8", "612", "M3U8 File", "2026-11-21 09:12", "file"),
               ("folder.jpg", "3,982,014", "JPG File", "2026-11-20 18:02", "file")]
REMOTE_FILES = [("..", "", "", "", "", "", "up"), ("artwork", "", "Directory", "2026-11-20 18:10", "drwxr-xr-x",
                                                   "paragon www", "folder"),
                ("01 Portal.flac", "31,224,118", "FLAC File", "2026-11-20 18:11", "-rw-r--r--", "paragon www", "file"),
                ("02 Ruins of Elsewhere.flac", "44,903,551", "FLAC File", "2026-11-20 18:12", "-rw-r--r--",
                 "paragon www", "file"),
                ("03 Static Bloom.mp3", "10,842,212", "MP3 File", "2026-11-20 18:12", "-rw-r--r--", "paragon www",
                 "file"),
                ("04 Signal Lost.mp3", "9,540,100", "MP3 File", "2026-11-20 18:13", "-rw-r--r--", "paragon www",
                 "file"),
                ("index.html", "4,207", "HTML File", "2026-11-21 10:03", "-rw-r--r--", "paragon www", "file")]
QUEUE = [("C:\\Users\\You\\Music\\Paragon\\ELSEWORLD\\05 Arc Light.mp3", "→", "/public_html/music/elseworld/05 Arc Light.mp3",
          "15,203,480", "Normal", 0.62),
         ("C:\\Users\\You\\Music\\Paragon\\ELSEWORLD\\ELSEWORLD.m3u8", "→", "/public_html/music/elseworld/ELSEWORLD.m3u8",
          "612", "Normal", None),
         ("C:\\Users\\You\\Music\\Paragon\\ELSEWORLD\\folder.jpg", "→", "/public_html/music/elseworld/folder.jpg",
          "3,982,014", "Normal", None)]
LOG = [("Status", "Resolving address of ftp.paragon-productions.example"),
       ("Status", "Connecting to 203.0.113.24:21..."),
       ("Status", "Connection established, waiting for welcome message..."),
       ("Response", "220 Paragon FTP server ready."),
       ("Command", "AUTH TLS"), ("Response", "234 Using authentication type TLS."),
       ("Status", "Initializing TLS..."), ("Status", "TLS connection established."),
       ("Command", "USER paragon"), ("Response", "331 Password required for paragon"),
       ("Command", "PASS ********"), ("Response", "230 Logged on"), ("Status", "Logged in"),
       ("Status", 'Retrieving directory listing of "/public_html/music/elseworld"...'),
       ("Command", "MLSD"), ("Response", '226 Successfully transferred "/public_html/music/elseworld"'),
       ("Status", 'Directory listing of "/public_html/music/elseworld" successful'),
       ("Status", 'Starting upload of C:\\Users\\You\\Music\\Paragon\\ELSEWORLD\\05 Arc Light.mp3')]


class Table(QAbstractTableModel):
    """Rows as a plain Python list (never QStandardItemModel: PR7-Z's crash); the last item names the icon."""

    def __init__(self, columns, rows, icon_col=True, right=()):
        super().__init__()
        self.columns, self.rows, self.icon_col, self.right = columns, rows, icon_col, set(right)
        self.icons = {k: file_icon(k) for k in ("up", "folder", "file", "drive", "server")}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.columns[s].upper() if o == Qt.Horizontal and role == Qt.DisplayRole else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            v = row[index.column()]
            return v if isinstance(v, str) else None
        if role == Qt.DecorationRole and index.column() == 0 and self.icon_col:
            return self.icons.get(row[-1])
        if role == Qt.TextAlignmentRole and index.column() in self.right:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.UserRole:
            return row[-1]
        return None


class FileView(QTreeView):
    """A file list; a selected row gets one family-gradient band across its width (as PR7-Z's list)."""

    def __init__(self, model, widths):
        super().__init__()
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(18, 18))
        self.setModel(model)
        for i, w in enumerate(widths):
            self.header().resizeSection(i, w)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(QHeaderView.Interactive)

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


class ProgressDelegate(QStyledItemDelegate):
    """The queue's Status column: a family-gradient bar for the file being transferred."""

    def paint(self, p, option, index):
        value = index.model().rows[index.row()][5]
        if value is None:
            super().paint(p, option, index)
            return
        r = QRectF(option.rect).adjusted(4, 5, -4, -5)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.setBrush(QColor(theme.WIDGET))
        p.drawRoundedRect(r, 3, 3)
        done = QRectF(r.left(), r.top(), r.width() * value, r.height())
        p.setPen(Qt.NoPen)
        p.setBrush(theme.family_gradient(r.left(), 0, r.right(), 0))
        p.drawRoundedRect(done, 3, 3)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, Qt.AlignCenter, f"{value:.0%}  ·  2.4 MB/s  ·  0:02 left")
        p.restore()


def _tree(rootname: str, path: list[str], kind: str) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderHidden(True)
    t.setIconSize(QSize(18, 18))
    item = QTreeWidgetItem([rootname])
    item.setIcon(0, file_icon(kind))
    t.addTopLevelItem(item)
    for name in path:
        child = QTreeWidgetItem([name])
        child.setIcon(0, file_icon("folder"))
        item.addChild(child)
        item.setExpanded(True)
        item = child
    t.setCurrentItem(item)
    t.setStyleSheet(f"QTreeView::item:selected {{ background: {theme.qss_gradient(theme.LIT, 0.22)}; color: #FFFFFF; }}"
                    " QTreeView::branch:selected { background: transparent; }")
    return t


def _site(title: str, path: str, tree: QTreeWidget, view: FileView, summary: str) -> QWidget:
    w = QWidget()
    col = QVBoxLayout(w)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(4)
    row = QHBoxLayout()
    lab = QLabel(title.upper())
    lab.setProperty("role", "field")
    row.addWidget(lab)
    box = QComboBox()
    box.setEditable(True)
    box.setEditText(path)
    row.addWidget(box, 1)
    col.addLayout(row)
    split = QSplitter(Qt.Vertical)
    split.addWidget(tree)
    split.addWidget(view)
    split.setSizes([150, 380])
    col.addWidget(split, 1)
    info = QLabel(summary)
    info.setProperty("role", "dim")
    col.addWidget(info)
    return w


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("paragon@ftp.paragon-productions.example - PR7-F")
        self.resize(1560, 1000)
        bar = self.menuBar()
        for title, items in MENUS.items():
            m = bar.addMenu(title)
            for it in items:
                if it == "-":
                    m.addSeparator()
                    continue
                text, _, sc = it.partition("\t")
                a = QAction(text, self)
                if sc:
                    a.setShortcut(QKeySequence(sc))
                m.addAction(a)
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(Header())
        tb = Toolbar()
        for k in ("log", "localtree", "remotetree", "queue"):
            tb.keys[k].setChecked(True)
        col.addWidget(tb)
        # Quickconnect: Host, Username, Password, Port, as FileZilla's bar.
        qc = QHBoxLayout()
        qc.setContentsMargins(16, 8, 16, 8)
        for label, value, width, secret in (("Host", "ftp.paragon-productions.example", 300, False),
                                            ("Username", "paragon", 160, False), ("Password", "secret", 160, True),
                                            ("Port", "", 70, False)):
            lab = QLabel(label.upper())
            lab.setProperty("role", "field")
            qc.addWidget(lab)
            e = QLineEdit(value)
            e.setFixedWidth(width)
            if secret:
                e.setEchoMode(QLineEdit.Password)
            qc.addWidget(e)
            qc.addSpacing(8)
        go = QPushButton("Quickconnect")
        go.setDefault(True)
        qc.addWidget(go)
        from PySide6.QtWidgets import QToolButton
        hist = QToolButton()
        hist.setArrowType(Qt.DownArrow)
        hist.setToolTip("Recent servers")
        hist.setFixedSize(34, 34)
        qc.addWidget(hist)
        qc.addStretch(1)
        col.addLayout(qc)

        main = QSplitter(Qt.Vertical)
        main.setContentsMargins(16, 0, 16, 0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        colours = {"Status": theme.TEXT_DIM, "Command": theme.TEXT, "Response": theme.LED_ORANGE,
                   "Error": theme.METER_RED}
        for kind, text in LOG:
            f = QTextCharFormat()
            f.setForeground(QColor(colours[kind]))
            self.log.textCursor().insertText(f"{kind + ':':<10}{text}\n", f)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)  # the newest lines, as FileZilla shows
        self.log.ensureCursorVisible()
        main.addWidget(self.log)

        sites = QSplitter(Qt.Horizontal)
        local = Table(["Filename", "Filesize", "Filetype", "Last modified"], LOCAL_FILES, right={1})
        lview = FileView(local, [300, 110, 120])
        lview.selectionModel().select(local.index(7, 0), lview.selectionModel().SelectionFlag.Select |
                                      lview.selectionModel().SelectionFlag.Rows)
        sites.addWidget(_site("Local site", "C:\\Users\\You\\Music\\Paragon\\ELSEWORLD\\",
                              _tree("C: (Windows)", ["Users", "You", "Music", "Paragon", "ELSEWORLD"], "drive"), lview,
                              "7 files and 2 directories. Total size: 115,696,087 bytes"))
        remote = Table(["Filename", "Filesize", "Filetype", "Last modified", "Permissions", "Owner/Group"],
                       REMOTE_FILES, right={1})
        rview = FileView(remote, [270, 110, 100, 150, 110])
        sites.addWidget(_site("Remote site", "/public_html/music/elseworld",
                              _tree("/", ["public_html", "music", "elseworld"], "server"), rview,
                              "5 files and 1 directory. Total size: 96,514,188 bytes"))
        main.addWidget(sites)

        queue = QTabWidget()
        q = Table(["Server/Local file", "Direction", "Remote file", "Size", "Priority", "Status"],
                  [r + ("file",) for r in QUEUE], icon_col=False, right={3})
        qv = FileView(q, [440, 90, 420, 110, 90])
        qv.setItemDelegateForColumn(5, ProgressDelegate(qv))
        queue.addTab(qv, "QUEUED FILES (3)")
        queue.addTab(QWidget(), "FAILED TRANSFERS")
        queue.addTab(QWidget(), "SUCCESSFUL TRANSFERS (4)")
        main.addWidget(queue)
        main.setSizes([170, 560, 200])
        col.addWidget(main, 1)
        self.setCentralWidget(central)

        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        lock = QLabel()
        from PySide6.QtGui import QPixmap
        pm = QPixmap(36, 36)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        draw_icon(p, "lock", QRectF(0, 0, 18, 18), QColor(theme.LED_ORANGE), 1.5)
        p.end()
        lock.setPixmap(pm)
        lock.setToolTip("Encrypted: FTP over TLS (TLS 1.3)")
        sb.addPermanentWidget(lock)
        for text in ("FTP OVER TLS", "Queue: 19.2 MB"):
            sb.addPermanentWidget(QLabel(text))
        sb.addWidget(QLabel("Uploading 05 Arc Light.mp3"), 1)
        self.setStatusBar(sb)
