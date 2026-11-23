import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Tests never touch the real PR7-F data (known hosts, sites) or Windows Credential Manager.
os.environ["PR7F_DATA"] = tempfile.mkdtemp(prefix="pr7f-data-")
os.environ["PR7F_MEMORY_KEYRING"] = "1"


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from pr7f import theme
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())
    yield app


@pytest.fixture
def server_root(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    (root / "music").mkdir()
    (root / "music" / "song.mp3").write_bytes(os.urandom(300_000))
    (root / "index.html").write_bytes(b"<html>hi</html>")
    return root


@pytest.fixture(params=["plain", "tls"])
def ftp_server(request, server_root, tmp_path):
    from servers import FTPServer
    s = FTPServer(str(server_root), tls=request.param == "tls", certdir=str(tmp_path))
    s.kind = request.param
    yield s
    s.stop()


@pytest.fixture
def sftp_server(server_root):
    from servers import SFTPServerThread
    s = SFTPServerThread(str(server_root))
    yield s
    s.stop()
