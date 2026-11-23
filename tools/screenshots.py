"""Screenshots of the mock-up (offscreen): python tools/screenshots.py OUT_DIR"""
import json
import os
import sys
import tempfile
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7f_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 3200, "height": 2200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from pr7f import theme  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setPalette(theme.palette())
app.setStyleSheet(theme.stylesheet())
from pr7f.main_window import MainWindow  # noqa: E402
from pr7f.site_manager import SiteManager  # noqa: E402

w = MainWindow()
w.show()
app.processEvents()
w.grab().save(str(out / "main_window.png"))
s = SiteManager(w)
s.show()
app.processEvents()
s.grab().save(str(out / "site_manager.png"))
print("ok")
