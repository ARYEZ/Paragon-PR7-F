"""Connection tabs, as FileZilla's: each tab its own connection, panes and log; the already-connected question;
one queue list for every tab; replies always reach the tab that asked."""

import os
import time

import pytest

from pr7f import remote, settings
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
def window(qapp, tmp_path):
    from pr7f.main_window import MainWindow
    local = tmp_path / "local"
    (local / "music").mkdir(parents=True)
    (local / "a.txt").write_bytes(b"from tab one")
    (local / "b.txt").write_bytes(b"from tab two")
    w = MainWindow(str(local))
    w.answers = {"cert": lambda p: "once", "hostkey": lambda p: "once", "exists": lambda ex: ("overwrite", False)}
    w.local_dir = local
    w.show()
    yield w
    settings.set("already_connected", "ask")
    w.close()


def ftp(server, name=""):
    return remote.Site("127.0.0.1", USER, PASSWORD, server.port, "ftp", name=name)


def sftp(server, name=""):
    return remote.Site("127.0.0.1", USER, PASSWORD, server.port, "sftp", name=name)


def connected(qapp, w, tab):
    assert tab.browser.wait_idle() and wait(qapp, lambda: tab.remote.path == "/")


def test_new_and_close_tabs(qapp, window):
    assert len(window.tabs) == 1 and window.tabbar.tabText(0) == "Not connected"
    t2 = window.new_tab()
    assert len(window.tabs) == 2 and window.tab is t2 and t2.local.path == str(window.local_dir)  # same local folder
    window.close_tab()
    assert len(window.tabs) == 1 and window.tabbar.count() == 1
    window.close_tab()                                                   # the last one stays
    assert len(window.tabs) == 1


def test_two_servers_in_two_tabs(qapp, window, ftp_server, sftp_server, server_root):
    t1 = window.tab
    window.connect_to(ftp(ftp_server, "Website"))
    connected(qapp, window, t1)
    t2 = window.new_tab()
    window.connect_to(sftp(sftp_server, "NAS"))
    connected(qapp, window, t2)
    assert [window.tabbar.tabText(i) for i in range(2)] == ["Website", "NAS"]
    assert window.windowTitle() == "NAS - PR7-F" and window.enc_text.text() == "SFTP"
    window.navigate("/music")                                            # in the NAS tab only
    assert t2.browser.wait_idle() and wait(qapp, lambda: t2.remote.path == "/music")
    assert t1.remote.path == "/"
    window.tabbar.setCurrentIndex(0)
    assert window.windowTitle() == "Website - PR7-F" and window.remote is t1.remote
    assert window.enc_text.text() in ("FTP OVER TLS", "FTP (NOT ENCRYPTED)")
    assert "Listing directory /music" in t2.logview.toPlainText()        # each tab its own log
    assert "Listing directory /music" not in t1.logview.toPlainText()


def test_already_connected_question(qapp, window, ftp_server, sftp_server):
    asked = []
    window.answers["already"] = lambda p: asked.append(p) or "new_tab"
    window.connect_to(ftp(ftp_server, "Website"))
    connected(qapp, window, window.tab)
    window.connect_to(sftp(sftp_server, "NAS"))
    assert asked == [("Website", "NAS")] and len(window.tabs) == 2      # asked, then a new tab
    connected(qapp, window, window.tabs[1])
    window.answers["already"] = lambda p: asked.append(p) or "replace"
    window.connect_to(ftp(ftp_server, "Website again"))
    assert len(window.tabs) == 2                                        # replaced this tab's connection
    assert window.tab.browser.wait_idle() and wait(qapp, lambda: window.tabbar.tabText(1) == "Website again")
    window.answers["already"] = lambda p: asked.append(p) or None       # Cancel: nothing happens
    window.connect_to(sftp(sftp_server, "NAS"))
    assert len(window.tabs) == 2 and window.tabbar.tabText(1) == "Website again"
    settings.set("already_connected", "new_tab")                        # "Always perform this action"
    n = len(asked)
    window.connect_to(sftp(sftp_server, "NAS"))
    assert len(asked) == n and len(window.tabs) == 3


def test_always_box_is_remembered(qapp):
    from pr7f.dialogs import AlreadyConnectedDialog
    d = AlreadyConnectedDialog("Website", "NAS")
    d.replace.setChecked(True)
    d.always.setChecked(True)
    assert d.answer() == "replace" and settings.get("already_connected") == "replace"
    settings.set("already_connected", "ask")


def test_replies_reach_the_tab_that_asked(qapp, window, ftp_server, sftp_server):
    t1 = window.tab
    window.connect_to(sftp(sftp_server, "NAS"))                          # still connecting ...
    t2 = window.new_tab()                                               # ... when another tab is opened
    connected(qapp, window, t1)
    assert t1.remote.path == "/" and window.tabbar.tabText(0) == "NAS"
    assert t2.remote.path == "" and window.tabbar.tabText(1) == "Not connected"
    assert window.windowTitle() == "PR7-F" and window.enc_text.text() == ""  # the shown tab is still unconnected


def test_one_queue_for_every_tab(qapp, window, ftp_server, sftp_server, server_root):
    t1 = window.tab
    window.connect_to(ftp(ftp_server, "Website"))
    connected(qapp, window, t1)
    window.upload([next(r for r in t1.local.model.rows if r.name == "a.txt")], start=True)
    t2 = window.new_tab()
    window.connect_to(sftp(sftp_server, "NAS"))
    connected(qapp, window, t2)
    window.upload([next(r for r in t2.local.model.rows if r.name == "b.txt")], start=True)
    assert wait(qapp, lambda: window.models["done"].rowCount() == 2)
    done = {window.models["done"].data(window.models["done"].index(i, 0)):
            window.models["done"].data(window.models["done"].index(i, 3)) for i in range(2)}
    assert done == {"Website": "/a.txt", "NAS": "/b.txt"}
    assert (server_root / "a.txt").read_bytes() == b"from tab one"
    assert (server_root / "b.txt").read_bytes() == b"from tab two"
    assert wait(qapp, lambda: "b.txt" in [r.name for r in t2.remote.model.rows])  # its own listing refreshed


def test_closing_a_busy_tab_asks(qapp, window, ftp_server, server_root):
    window.connect_to(ftp(ftp_server, "Website"))
    connected(qapp, window, window.tab)
    t2 = window.new_tab()
    window.connect_to(ftp(ftp_server, "Second"))
    connected(qapp, window, t2)
    window.upload([next(r for r in t2.local.model.rows if r.name == "a.txt")])  # queued, not started
    window.answers["close_busy_tab"] = lambda tab: False
    window.close_tab()
    assert len(window.tabs) == 2
    window.answers["close_busy_tab"] = lambda tab: True
    window.close_tab()
    assert len(window.tabs) == 1 and window.tabbar.tabText(0) == "Website"


def test_sync_and_compare_belong_to_their_tab(qapp, window, ftp_server):
    window.connect_to(ftp(ftp_server, "Website"))
    connected(qapp, window, window.tab)
    window.toggle_compare()
    window.toggle_sync()
    assert window.toolbar.keys["sync"].isChecked() and window.toolbar.keys["compare"].isChecked()
    window.new_tab()
    assert not window.toolbar.keys["sync"].isChecked() and not window.toolbar.keys["compare"].isChecked()
    window.tabbar.setCurrentIndex(0)
    assert window.toolbar.keys["sync"].isChecked() and window.toolbar.keys["compare"].isChecked()
