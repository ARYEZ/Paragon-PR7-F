"""The window against real servers, driven as a user would: connect, browse, transfer, manage files, sites."""

import os
import time

import pytest

from pr7f import remote, settings, sites
from servers import PASSWORD, USER


def wait(qapp, cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def local_dir(tmp_path):
    d = tmp_path / "local"
    d.mkdir()
    (d / "Album").mkdir()
    (d / "Album" / "01 Portal.flac").write_bytes(os.urandom(250_000))
    (d / "Album" / "cover.jpg").write_bytes(os.urandom(40_000))
    (d / "notes.txt").write_bytes(b"local notes")
    return d


@pytest.fixture
def window(qapp, local_dir, monkeypatch):
    from pr7f.main_window import MainWindow
    monkeypatch.setattr("pr7f.main_window.QMessageBox.question", lambda *a, **k: __import__(
        "PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
    w = MainWindow(str(local_dir))
    asked = []
    w.answers = {"cert": lambda p: asked.append(("cert", p["host"])) or "once",
                 "hostkey": lambda p: asked.append(("hostkey", p["kind"])) or "once",
                 "exists": lambda ex: asked.append(("exists", ex.item.remote)) or ("overwrite", False),
                 "no_open": True}
    w.asked = asked
    w.show()
    yield w
    w.close()


def connect(qapp, w, port, host="127.0.0.1"):
    w.qc["host"].setText(host)
    w.qc["user"].setText(USER)
    w.qc["password"].setText(PASSWORD)
    w.qc["port"].setText(str(port))
    w.quickconnect()
    assert w.browser.wait_idle()
    assert wait(qapp, lambda: w.remote.path == "/")


def names(model):
    return sorted(r.name for r in model.rows if r.kind not in ("up", "drive"))


def select(view, model, wanted):
    from PySide6.QtCore import QItemSelectionModel
    sm = view.selectionModel()
    sm.clearSelection()
    for i, r in enumerate(model.rows):
        if r.name in wanted:
            sm.select(model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def test_ftp_connect_encrypted_when_offered(qapp, window, ftp_server):
    connect(qapp, window, ftp_server.port)
    assert names(window.remote.model) == ["index.html", "music"]
    if ftp_server.kind == "tls":
        assert window.enc_text.text() == "FTP OVER TLS" and window.asked == [("cert", "127.0.0.1")]
        assert "TLS connection established" in window.logview.toPlainText()
    else:
        assert window.enc_text.text() == "FTP (NOT ENCRYPTED)" and window.asked == []
    assert window.windowTitle() == f"{USER}@127.0.0.1 - PR7-F"
    assert sites.recent()[0]["host"] == "127.0.0.1"
    assert PASSWORD not in window.logview.toPlainText()


def test_sftp_by_port_22_rule_and_host_key(qapp, window, sftp_server):
    window.qc["host"].setText(f"sftp://127.0.0.1")
    window.qc["user"].setText(USER)
    window.qc["password"].setText(PASSWORD)
    window.qc["port"].setText(str(sftp_server.port))
    window.quickconnect()
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/")
    assert window.enc_text.text() == "SFTP" and window.asked == [("hostkey", "ecdsa-sha2-nistp256")]
    assert names(window.remote.model) == ["index.html", "music"]


def test_wrong_password(qapp, window, ftp_server):
    window.qc["host"].setText("127.0.0.1")
    window.qc["user"].setText(USER)
    window.qc["password"].setText("wrong")
    window.qc["port"].setText(str(ftp_server.port))
    window.quickconnect()
    assert window.browser.wait_idle()
    assert "Login refused" in window.logview.toPlainText() and window.status_text.text() == "Could not connect"
    assert window.windowTitle() == "PR7-F"


def test_upload_and_download_by_double_click_and_drop(qapp, window, ftp_server, server_root, local_dir):
    connect(qapp, window, ftp_server.port)
    row = next(r for r in window.local.model.rows if r.name == "notes.txt")
    window.local.on_open_file([row])                                  # double-click: transfers at once
    assert wait(qapp, lambda: (server_root / "notes.txt").exists() and "notes.txt" in names(window.remote.model))
    assert (server_root / "notes.txt").read_bytes() == b"local notes"
    window._dropped_remote("local", ["Album"], "music")              # dragged onto the "music" folder
    assert wait(qapp, lambda: (server_root / "music" / "Album" / "cover.jpg").exists() and
                not window.queue.snapshot()["queued"])
    assert (server_root / "music" / "Album" / "01 Portal.flac").read_bytes() == \
        (local_dir / "Album" / "01 Portal.flac").read_bytes()
    window.navigate("/music")
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music")
    window._dropped_local("remote", ["song.mp3"], "")                 # and back down
    assert wait(qapp, lambda: (local_dir / "song.mp3").exists() and not window.queue.snapshot()["queued"])
    assert (local_dir / "song.mp3").read_bytes() == (server_root / "music" / "song.mp3").read_bytes()
    assert wait(qapp, lambda: "song.mp3" in names(window.local.model))  # the local list refreshed itself
    assert window.models["done"].rowCount() >= 4 and "SUCCESSFUL TRANSFERS" in window.queue_tabs.tabText(2)


def test_file_exists_question(qapp, window, ftp_server, server_root):
    (server_root / "notes.txt").write_bytes(b"server notes")
    connect(qapp, window, ftp_server.port)
    window.answers["exists"] = lambda ex: window.asked.append(("exists", ex.item.remote)) or ("skip", False)
    window.upload([next(r for r in window.local.model.rows if r.name == "notes.txt")], start=True)
    assert wait(qapp, lambda: window.queue.snapshot()["done"])
    assert ("exists", "/notes.txt") in window.asked and (server_root / "notes.txt").read_bytes() == b"server notes"


def test_remote_file_management(qapp, window, sftp_server, server_root):
    connect(qapp, window, sftp_server.port, host="sftp://127.0.0.1")
    window.remote_mkdir("Gigs")
    assert window.browser.wait_idle() and wait(qapp, lambda: "Gigs" in names(window.remote.model))
    row = next(r for r in window.remote.model.rows if r.name == "index.html")
    window.remote_rename(row, "home.html")
    assert window.browser.wait_idle() and wait(qapp, lambda: "home.html" in names(window.remote.model))
    row = next(r for r in window.remote.model.rows if r.name == "home.html")
    window.remote_chmod([row], 0o600)
    assert window.browser.wait_idle()
    if os.name != "nt":  # the test server keeps files on this disk: NTFS has no Unix permissions to keep
        assert wait(qapp, lambda: next(
            (r.perms for r in window.remote.model.rows if r.name == "home.html"), "") == "-rw-------")
    assert "Error" not in window.logview.toPlainText().split("Gigs")[-1]  # the server took the change
    window.remote_delete([next(r for r in window.remote.model.rows if r.name == "music")], confirm=False)  # a folder
    assert window.browser.wait_idle() and wait(qapp, lambda: "music" not in names(window.remote.model))
    assert sorted(os.listdir(server_root)) == ["Gigs", "home.html"]


def test_local_file_management(qapp, window, local_dir):
    window.local_mkdir("New Stuff")
    assert (local_dir / "New Stuff").is_dir() and "New Stuff" in names(window.local.model)
    window.local_rename(next(r for r in window.local.model.rows if r.name == "notes.txt"), "readme.txt")
    assert (local_dir / "readme.txt").read_bytes() == b"local notes"
    window.local_delete([next(r for r in window.local.model.rows if r.name == "New Stuff")], confirm=False)
    assert not (local_dir / "New Stuff").exists()
    window.local._double(window.local.model.index(next(i for i, r in enumerate(window.local.model.rows)
                                                          if r.name == "Album"), 0))
    assert window.local.path == str(local_dir / "Album") and names(window.local.model) == ["01 Portal.flac", "cover.jpg"]
    window.local.up()
    assert window.local.path == str(local_dir)


def test_compare_and_sync_browsing(qapp, window, ftp_server, server_root, local_dir):
    (local_dir / "index.html").write_bytes(b"<html>different</html>")
    (local_dir / "music").mkdir()
    window.local.refresh()
    connect(qapp, window, ftp_server.port)
    window.toggle_compare()
    assert window.local.model.marks["index.html"] == "differs" and window.local.model.marks["notes.txt"] == "only"
    assert window.remote.model.marks["index.html"] == "differs" and "music" not in window.remote.model.marks
    window.toggle_sync()
    assert window.toolbar.keys["sync"].isChecked() and window.toolbar.keys["compare"].isChecked()
    window.local.go(str(local_dir / "music"))                       # local into music: remote follows
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music")
    window.navigate("/")                                            # remote back up: local follows
    assert window.browser.wait_idle() and wait(qapp, lambda: window.local.path == str(local_dir))


def test_view_edit_uploads_the_changed_file(qapp, window, ftp_server, server_root):
    connect(qapp, window, ftp_server.port)
    window.view_edit(next(r for r in window.remote.model.rows if r.name == "index.html"))
    assert window.browser.wait_idle() and wait(qapp, lambda: window.edited)
    copy = next(iter(window.edited))
    assert open(copy, "rb").read() == b"<html>hi</html>"
    with open(copy, "wb") as fh:
        fh.write(b"<html>edited in PR7-W</html>")
    window.answers["upload_edited"] = lambda path: True
    window._edited_changed(copy)                                   # what the file watcher reports on save
    assert wait(qapp, lambda: (server_root / "index.html").read_bytes() == b"<html>edited in PR7-W</html>")


def test_site_manager_saves_and_connects(qapp, window, sftp_server, monkeypatch):
    from pr7f.site_manager import SiteManager
    dlg = SiteManager(window)
    s = dlg.new_site()
    dlg.protocol.setCurrentIndex(1)                                 # SFTP
    dlg.host.setText("127.0.0.1")
    dlg.port.setText(str(sftp_server.port))
    dlg.user.setText(USER)
    dlg.password.setText(PASSWORD)
    dlg.remote_dir.setText("/music")
    assert not dlg.encryption.isVisible() and [dlg.logon.itemData(i) for i in range(dlg.logon.count())] == [
        "normal", "ask", "key"]
    dlg.connect_site()
    saved = sites.load_sites()
    assert saved[-1]["host"] == "127.0.0.1" and "password" not in saved[-1]          # never in the file
    assert PASSWORD not in open(os.path.join(sites.data_dir(), "sites.json"), encoding="utf-8").read()
    assert sites.get_password(s["id"]) == PASSWORD                                    # in the credential store
    window.connect_to(dlg.chosen)
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music")
    assert names(window.remote.model) == ["song.mp3"]
    dlg2 = SiteManager(window, select=s["id"])
    assert dlg2.password.text() == PASSWORD and dlg2.remote_dir.text() == "/music"
    monkeypatch.setattr("pr7f.site_manager.QMessageBox.question", lambda *a, **k: __import__(
        "PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
    dlg2.delete()
    dlg2.accept()
    assert all(x["id"] != s["id"] for x in sites.load_sites()) and sites.get_password(s["id"]) == ""


def test_disconnect_and_queue_needs_a_connection(qapp, window, ftp_server, monkeypatch):
    shown = []
    monkeypatch.setattr("pr7f.main_window.QMessageBox.information", lambda *a: shown.append(a[2]))
    window.upload([next(r for r in window.local.model.rows if r.name == "notes.txt")])
    assert shown == ["Connect to a server first."]
    connect(qapp, window, ftp_server.port)
    window.disconnect()
    assert window.browser.wait_idle()
    assert not window.browser.connected and window.remote.model.rowCount() == 0
    assert window.remote.info.text() == "Not connected to any server"


def test_quickconnect_history_and_settings(qapp, window, ftp_server):
    connect(qapp, window, ftp_server.port)
    window._fill_quick(sites.recent()[0])
    assert window.qc["host"].text() == "127.0.0.1" and window.qc["port"].text() == str(ftp_server.port)
    assert window.qc["password"].text() == PASSWORD  # (unchanged: the history never holds passwords)
    from pr7f.dialogs import SettingsDialog
    d = SettingsDialog(window)
    d.workers.setValue(4)
    d.apply()
    assert settings.get_int("transfers", 2) == 4
    settings.set("transfers", 2)
