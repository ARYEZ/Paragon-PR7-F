"""Screenshots of the real window (offscreen), connected to a local test server:
python tools/screenshots.py OUT_DIR"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7f_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 3200, "height": 2200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
os.environ["PR7F_DATA"] = tempfile.mkdtemp()
os.environ["PR7F_MEMORY_KEYRING"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
from pr7f import sites, theme  # noqa: E402
from servers import PASSWORD, USER, FTPServer  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp())
local = work / "Music" / "Paragon" / "ELSEWORLD"
local.mkdir(parents=True)
for name, n in (("01 Portal.flac", 31_224_118), ("02 Ruins of Elsewhere.flac", 44_903_551),
                ("03 Static Bloom.mp3", 10_842_212), ("04 Signal Lost.mp3", 9_540_100), ("05 Arc Light.mp3", 15_203_480),
                ("ELSEWORLD.m3u8", 612), ("folder.jpg", 3_982_014)):
    with open(local / name, "wb") as fh:
        fh.truncate(n)
(local / "Artwork").mkdir()
server = work / "server"
(server / "public_html" / "music" / "elseworld" / "artwork").mkdir(parents=True)
for name in ("01 Portal.flac", "02 Ruins of Elsewhere.flac", "03 Static Bloom.mp3"):
    with open(server / "public_html" / "music" / "elseworld" / name, "wb") as fh:
        fh.truncate((local / name).stat().st_size)
(server / "public_html" / "music" / "elseworld" / "index.html").write_bytes(b"x" * 4207)
srv = FTPServer(str(server), True, str(work))

app = QApplication([])
theme.load_fonts()
app.setPalette(theme.palette())
app.setStyleSheet(theme.stylesheet())
from pr7f.main_window import MainWindow  # noqa: E402

w = MainWindow(str(local))
w.answers = {"cert": lambda p: "once", "exists": lambda ex: ("overwrite", False)}
w.show()
w.qc["host"].setText("127.0.0.1")
w.qc["user"].setText(USER)
w.qc["password"].setText(PASSWORD)
w.qc["port"].setText(str(srv.port))
s = sites.new_site("Paragon website")
s.update(host="ftp.paragon-productions.example", user="paragon", remote_dir="/public_html/music")
sites.save_sites([s, dict(sites.new_site("Paragon NAS (SFTP)"), protocol="sftp", host="nas.local", user="paragon")])
w.quickconnect()
w.browser.wait_idle()
w.navigate("/public_html/music/elseworld")
w.browser.wait_idle()
from PySide6.QtCore import QItemSelectionModel  # noqa: E402
for i, r in enumerate(w.local.model.rows):
    if r.name in ("04 Signal Lost.mp3", "05 Arc Light.mp3"):
        w.local.list.selectionModel().select(w.local.model.index(i, 0), QItemSelectionModel.Select |
                                             QItemSelectionModel.Rows)
w.upload(w.local.selected(), start=True)
end = time.monotonic() + 30
while time.monotonic() < end and w.queue.snapshot()["queued"]:
    app.processEvents()
    time.sleep(0.02)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
w.grab().save(str(out / "main_window.png"))
from pr7f.site_manager import SiteManager  # noqa: E402
sm = SiteManager(w)
sm.show()
app.processEvents()
sm.grab().save(str(out / "site_manager.png"))
srv.stop()
print("ok")
