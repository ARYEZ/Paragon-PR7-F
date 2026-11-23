"""Custom-painted Paragon widgets: the PR7-F mark, the header, compact piano-black keys and line icons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient, QRegion, QTransform)
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget

from . import theme

# --------------------------------------------------------------------------- the PR7-F mark
# Same construction as the PR7 plugins' Logo.cpp: letters designed 1 unit tall, upright,
# stems 0.24 wide, bars 0.2 tall, then slanted 0.3; two horizontal "speed cuts".
SLANT = 0.3
SPACING = 0.1
WIDTHS = [0.8, 0.84, 0.8, 0.4, 0.72]  # P, R, 7, dash, F
TOTAL_WIDTH = sum(WIDTHS) + 4 * SPACING + SLANT
CUTS = [(0.63, 0.68), (0.79, 0.83)]


def _poly(path: QPainterPath, pts, x: float) -> None:
    path.moveTo(pts[0][0] + x, pts[0][1])
    for px, py in pts[1:]:
        path.lineTo(px + x, py)
    path.closeSubpath()


# F: a 0.24 stem, a 0.2 top bar and a shorter middle bar (at the dash's height, clear of the speed cuts).
F_SHAPE = [(0, 0), (.72, 0), (.72, .2), (.24, .2), (.24, .42), (.6, .42), (.6, .6), (.24, .6), (.24, 1), (0, 1)]
SEVEN_SHAPE = [(0, 0), (.8, 0), (.8, .2), (.44, 1), (.18, 1), (.5, .2), (0, .2)]


def _lean() -> QTransform:
    return QTransform(1, 0, -SLANT, 1, SLANT, 0)  # x' = x + slant*(1 - y): y is down, the top leans right


def _letters() -> tuple[QPainterPath, QPainterPath]:
    """(P, R, dash, Z) and the 7, in letter units with y down, slanted."""
    main, seven = QPainterPath(), QPainterPath()
    main.setFillRule(Qt.OddEvenFill)  # bowl counters are holes
    bowl = [(0, 0), (.64, 0), (.8, .15), (.8, .45), (.64, .6), (.24, .6), (.24, 1), (0, 1)]
    counter = [(.24, .2), (.56, .2), (.56, .4), (.24, .4)]
    x = 0.0
    _poly(main, bowl, x); _poly(main, counter, x)
    x += WIDTHS[0] + SPACING
    _poly(main, bowl, x); _poly(main, counter, x)
    _poly(main, [(.4, .6), (.64, .6), (.84, 1), (.6, 1)], x)  # R's leg
    x += WIDTHS[1] + SPACING
    _poly(seven, [(0, 0), (.8, 0), (.8, .2), (.44, 1), (.18, 1), (.5, .2), (0, .2)], x)
    x += WIDTHS[2] + SPACING
    _poly(main, [(0, .42), (.4, .42), (.4, .6), (0, .6)], x)  # dash, clear of the cuts
    x += WIDTHS[3] + SPACING
    _poly(main, F_SHAPE, x)
    # Lean forward: the top moves right, the baseline stays.
    lean = QTransform(1, 0, -SLANT, 1, SLANT, 0)  # x' = x + slant*(1 - y): y is down, so the top leans right
    return lean.map(main), lean.map(seven)


_MAIN, _SEVEN = _letters()


def draw_mark(p: QPainter, area: QRectF, glow: bool = True) -> QRectF:
    h = min(area.height(), area.width() / TOTAL_WIDTH)
    bounds = QRectF(area.x(), area.center().y() - h / 2, TOTAL_WIDTH * h, h)
    place = QTransform().translate(bounds.x(), bounds.y()).scale(h, h)
    main, seven = place.map(_MAIN), place.map(_SEVEN)
    sev_grad = theme.family_gradient(bounds.x(), 0, bounds.right(), 0)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if glow:  # a soft neon halo behind the 7
        for ring in (3, 2, 1):
            c = QColor(theme.GLOW); c.setAlphaF(0.1 * (4 - ring))
            p.setPen(QPen(c, h * 0.07 * ring, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(seven)
    clip = QRegion(bounds.adjusted(-h, -h, h, h).toAlignedRect())
    for top, bottom in CUTS:
        clip -= QRegion(QRectF(bounds.x() - h, bounds.y() + h * top, bounds.width() + 2 * h,
                               h * (bottom - top)).toAlignedRect())
    p.setClipRegion(clip)
    p.setPen(Qt.NoPen)
    p.fillPath(main, QColor(theme.TEXT))
    p.fillPath(seven, sev_grad)
    p.restore()
    return bounds


class Header(QWidget):
    """64 px family header: PARAGON and the PR7-F mark, a subtitle; the current finish on the right."""

    def __init__(self, subtitle: str = "FILE TRANSFER", parent=None):
        super().__init__(parent)
        self.subtitle = subtitle
        self.setFixedHeight(64)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(theme.BACKGROUND))
        glow = QRadialGradient(QPointF(170, 0), 420)
        c = QColor(theme.GLOW); c.setAlphaF(0.07)
        glow.setColorAt(0, c); glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(r, glow)
        f = QFont("Inter", 1); f.setPixelSize(21)
        p.setFont(f); p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(22, 0, 200, r.height()), Qt.AlignVCenter | Qt.AlignLeft, "PARAGON")
        mark = draw_mark(p, QRectF(140, 19, 200, 26))
        f2 = QFont("Inter", 1); f2.setPixelSize(12); f2.setWeight(QFont.DemiBold)
        p.setFont(f2); p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(mark.right() + 16, 0, 300, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.subtitle)
        p.drawText(QRectF(0, 0, r.width() - 22, r.height()), Qt.AlignVCenter | Qt.AlignRight, theme.FINISH.upper())
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.drawLine(0, r.height() - 1, r.width(), r.height() - 1)




# --------------------------------------------------------------------------- line icons (24x24)
def _folder(p: QPainterPath, dx: float = 0, dy: float = 0, k: float = 1.0) -> None:
    pts = [(2.5, 6), (9, 6), (11, 8.5), (21.5, 8.5), (21.5, 19.5), (2.5, 19.5)]
    p.moveTo(dx + pts[0][0] * k, dy + pts[0][1] * k)
    for x, y in pts[1:]:
        p.lineTo(dx + x * k, dy + y * k)
    p.closeSubpath()


def _icon_path(name: str) -> QPainterPath:
    p = QPainterPath()
    if name == "sitemanager":      # stacked servers
        for y in (3.5, 10, 16.5):
            p.addRoundedRect(QRectF(3, y, 18, 5), 1.2, 1.2)
            p.addEllipse(QRectF(16, y + 1.8, 1.5, 1.5))
    elif name == "log":            # a page of lines
        p.addRoundedRect(QRectF(4, 3, 16, 18), 2, 2)
        for y in (8, 12, 16):
            p.moveTo(7.5, y); p.lineTo(16.5, y)
    elif name in ("localtree", "remotetree"):
        p.moveTo(5, 4); p.lineTo(5, 18); p.lineTo(10, 18); p.moveTo(5, 11); p.lineTo(10, 11)
        p.addRoundedRect(QRectF(10, 8.5, 10, 5), 1, 1); p.addRoundedRect(QRectF(10, 15.5, 10, 5), 1, 1)
        if name == "remotetree":
            p.addRoundedRect(QRectF(2.5, 1.5, 5, 3.5), 1, 1)
    elif name == "queue":          # up and down arrows over a list
        p.moveTo(7, 15); p.lineTo(7, 3.5); p.moveTo(4, 6.5); p.lineTo(7, 3.5); p.lineTo(10, 6.5)
        p.moveTo(17, 3.5); p.lineTo(17, 15); p.moveTo(14, 12); p.lineTo(17, 15); p.lineTo(20, 12)
        p.moveTo(3.5, 19.5); p.lineTo(20.5, 19.5)
    elif name == "refresh":
        p.moveTo(19, 12); p.arcTo(QRectF(5, 5, 14, 14), 0, 290)
        p.moveTo(19.5, 6); p.lineTo(19, 11.5); p.lineTo(14, 10.5)
    elif name == "process":        # play
        p.moveTo(7, 4.5); p.lineTo(19, 12); p.lineTo(7, 19.5); p.closeSubpath()
    elif name == "cancel":
        p.addEllipse(QRectF(3, 3, 18, 18)); p.moveTo(8.5, 8.5); p.lineTo(15.5, 15.5)
        p.moveTo(15.5, 8.5); p.lineTo(8.5, 15.5)
    elif name in ("disconnect", "reconnect"):  # a plug, apart or together
        gap = 2.5 if name == "disconnect" else 0
        p.addRoundedRect(QRectF(4, 9 - gap / 2, 7, 6), 1.5, 1.5)
        p.moveTo(11, 10.5 - gap / 2); p.lineTo(13.5 - gap / 2 + gap, 10.5 - gap / 2)
        p.moveTo(11, 13.5 - gap / 2); p.lineTo(13.5 - gap / 2 + gap, 13.5 - gap / 2)
        p.addRoundedRect(QRectF(13.5 + gap, 9 + gap / 2, 6.5, 6), 1.5, 1.5)
        p.moveTo(2, 12 - gap / 2); p.lineTo(4, 12 - gap / 2); p.moveTo(20 + gap, 12 + gap / 2); p.lineTo(22, 12 + gap / 2)
    elif name == "filter":         # funnel
        p.moveTo(3.5, 4.5); p.lineTo(20.5, 4.5); p.lineTo(14, 12.5); p.lineTo(14, 19.5); p.lineTo(10, 17.5)
        p.lineTo(10, 12.5); p.closeSubpath()
    elif name == "compare":        # two columns
        p.addRoundedRect(QRectF(3, 4, 7.5, 16), 1.5, 1.5); p.addRoundedRect(QRectF(13.5, 4, 7.5, 16), 1.5, 1.5)
        for y in (8.5, 12, 15.5):
            p.moveTo(5, y); p.lineTo(8.5, y); p.moveTo(15.5, y); p.lineTo(19, y)
    elif name == "sync":           # two arrows, one each way
        p.moveTo(4, 9); p.lineTo(19, 9); p.moveTo(15.5, 5.5); p.lineTo(19, 9); p.lineTo(15.5, 12.5)
        p.moveTo(20, 15); p.lineTo(5, 15); p.moveTo(8.5, 11.5); p.lineTo(5, 15); p.lineTo(8.5, 18.5)
    elif name == "search":
        p.addEllipse(QRectF(3.5, 3.5, 12, 12)); p.moveTo(14, 14); p.lineTo(20.5, 20.5)
    elif name == "folder":
        _folder(p)
    elif name == "up":
        _folder(p)
        p.moveTo(12, 17); p.lineTo(12, 11); p.moveTo(9.5, 13.5); p.lineTo(12, 11); p.lineTo(14.5, 13.5)
    elif name == "file":
        p.moveTo(5, 2.5); p.lineTo(14, 2.5); p.lineTo(19, 7.5); p.lineTo(19, 21.5); p.lineTo(5, 21.5)
        p.closeSubpath(); p.moveTo(14, 2.5); p.lineTo(14, 7.5); p.lineTo(19, 7.5)
    elif name == "drive":
        p.addRoundedRect(QRectF(3, 7, 18, 10), 2, 2); p.addEllipse(QRectF(16, 11, 2, 2))
    elif name == "server":
        p.addRoundedRect(QRectF(4, 3, 16, 7.5), 1.5, 1.5); p.addRoundedRect(QRectF(4, 13.5, 16, 7.5), 1.5, 1.5)
        p.addEllipse(QRectF(15.5, 6, 1.6, 1.6)); p.addEllipse(QRectF(15.5, 16.5, 1.6, 1.6))
    elif name == "lock":
        p.addRoundedRect(QRectF(5, 10.5, 14, 10), 2, 2)
        p.moveTo(8, 10.5); p.lineTo(8, 7.5); p.arcTo(QRectF(8, 3.5, 8, 8), 180, -180); p.lineTo(16, 10.5)
    elif name in ("upload", "download"):
        if name == "upload":
            p.moveTo(12, 17); p.lineTo(12, 4); p.moveTo(7.5, 8.5); p.lineTo(12, 4); p.lineTo(16.5, 8.5)
        else:
            p.moveTo(12, 4); p.lineTo(12, 17); p.moveTo(7.5, 12.5); p.lineTo(12, 17); p.lineTo(16.5, 12.5)
        p.moveTo(4, 20.5); p.lineTo(20, 20.5)
    return p


def draw_icon(p: QPainter, name: str, rect: QRectF, colour, width: float = 1.7, fill: QColor | None = None) -> None:
    path = _icon_path(name)
    s = min(rect.width(), rect.height()) / 24.0
    t = QTransform().translate(rect.center().x() - 12 * s, rect.center().y() - 12 * s).scale(s, s)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if fill is not None:
        p.fillPath(t.map(path), fill)
    p.setPen(QPen(colour, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(t.map(path))
    p.restore()


def file_icon(kind: str, size: int = 18) -> QIcon:
    """Folder: orange line, faint fill. File: pearl grey. Drive / server: family red."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r = QRectF(0, 0, size, size)
    if kind in ("folder", "up"):
        fill = QColor(theme.LED_ORANGE)
        fill.setAlphaF(0.16)
        draw_icon(p, kind, r, QColor(theme.LED_ORANGE), 1.4, fill)
    elif kind in ("drive", "server"):
        draw_icon(p, kind, r, QColor(theme.ACCENT), 1.4)
    else:
        draw_icon(p, "file", r, QColor(theme.TEXT_DIM), 1.3)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- compact piano-black keys
class SmallKey(QAbstractButton):
    """A compact family piano-black key: icon only (the tooltip names it). Checkable keys (the log, the trees,
    the queue, sync browsing) show the family gradient bar at their foot when on."""

    def __init__(self, icon: str, tip: str, checkable: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setToolTip(tip)
        self.setCheckable(checkable)
        self.setFixedSize(QSize(38, 34))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        down, hover = self.isDown(), self.underMouse() and self.isEnabled()
        r = QRectF(self.rect()).adjusted(2, 1, -2, -4)
        if down:
            r.translate(0, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110 if down else 150))
        p.drawRoundedRect(r.translated(0, 2), 5, 5)
        ch = QLinearGradient(r.topLeft(), r.bottomLeft())
        for pos, c in ((0, "#57565C"), (.18, "#2A292E"), (.7, "#111113"), (1, "#020203")):
            ch.setColorAt(pos, QColor(c))
        p.setBrush(ch)
        p.drawRoundedRect(r, 5, 5)
        face = r.adjusted(2, 2, -2, -3)
        tf = QLinearGradient(face.topLeft(), face.bottomLeft())
        tf.setColorAt(0, QColor("#1C1B20"))
        tf.setColorAt(1, QColor("#060607"))
        p.setBrush(tf)
        p.drawRoundedRect(face, 3.5, 3.5)
        p.setPen(QPen(QColor(255, 255, 255, 105), 1))
        p.drawLine(QPointF(face.left() + 3, face.top() + 0.5), QPointF(face.right() - 3, face.top() + 0.5))
        if hover:
            c = QColor(theme.GLOW)
            c.setAlphaF(0.8)
            p.setPen(QPen(c, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), 5.5, 5.5)
        if self.isChecked():
            bar = QRectF(face.left() + 6, face.bottom() - 3, face.width() - 12, 2)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.family_gradient(bar.left(), 0, bar.right(), 0))
            p.drawRoundedRect(bar, 1, 1)
        colour = QColor("#FFFFFF") if (hover or down or self.isChecked()) else QColor(theme.ON_DARK)
        if not self.isEnabled():
            colour = QColor(theme.TEXT_DIM)
        draw_icon(p, self.icon_name, QRectF(face.center().x() - 9, face.center().y() - 9.5, 18, 18), colour, 1.6)


class Toolbar(QWidget):
    """FileZilla's toolbar, in its order: Site Manager | message log, local tree, remote tree, queue | refresh,
    process queue, cancel, disconnect, reconnect | filter, compare, synchronised browsing, search."""

    triggered = Signal(str)
    GROUPS = [[("sitemanager", "Site Manager (Ctrl+S)", False)],
              [("log", "Message log", True), ("localtree", "Local directory tree", True),
               ("remotetree", "Remote directory tree", True), ("queue", "Transfer queue", True)],
              [("refresh", "Refresh (F5)", False), ("process", "Process queue", False),
               ("cancel", "Cancel current operation", False), ("disconnect", "Disconnect", False),
               ("reconnect", "Reconnect", False)],
              [("filter", "Directory listing filters (Ctrl+I)", False), ("compare", "Directory comparison", True),
               ("sync", "Synchronised browsing (Ctrl+Y)", True), ("search", "Search remote files (F3)", False)]]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 7, 14, 7)
        lay.setSpacing(3)
        self.keys: dict[str, SmallKey] = {}
        for i, group in enumerate(self.GROUPS):
            if i:
                sep = QLabel()
                sep.setFixedSize(1, 24)
                sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
                lay.addSpacing(6)
                lay.addWidget(sep)
                lay.addSpacing(6)
            for name, tip, checkable in group:
                k = SmallKey(name, tip, checkable)
                k.clicked.connect(lambda _=False, n=name: self.triggered.emit(n))
                self.keys[name] = k
                lay.addWidget(k)
        lay.addStretch(1)
