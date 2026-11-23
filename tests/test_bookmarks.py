"""Bookmarks: global and per site, the menu, opening one (both sides, synchronised browsing, comparison)."""

import json
import os
import time

import pytest

from pr7f import bookmarks, sites
from pr7f.bookmarks import Bookmark
from servers import PASSWORD, USER


def wait(qapp, cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def clean():
    bookmarks.save_global([])
    sites.save_sites([])
    yield
    bookmarks.save_global([])
    sites.save_sites([])


@pytest.fixture
def window(qapp, tmp_path):
    from pr7f.main_window import MainWindow
    local = tmp_path / "local"
    (local / "music" / "live").mkdir(parents=True)
    w = MainWindow(str(local))
    w.answers = {"cert": lambda p: "once", "hostkey": lambda p: "once"}
    w.local_dir = local
    w.show()
    yield w
    w.close()


def connect_site(qapp, w, server, protocol="ftp"):
    """Through the Site Manager, so the connection has a site (site bookmarks need one)."""
    d = sites.new_site("Paragon website")
    d.update(host="127.0.0.1", port=server.port, user=USER, protocol=protocol)
    sites.save_sites([d])
    sites.set_password(d["id"], PASSWORD)
    w.connect_to(sites.to_site(d))
    assert w.browser.wait_idle() and wait(qapp, lambda: w.remote.path == "/")
    return d["id"]


def test_storage():
    bookmarks.save_global([Bookmark("Music", "C:\\Music", "/music", True)])
    assert bookmarks.load_global() == [Bookmark("Music", "C:\\Music", "/music", True, False)]
    d = sites.new_site("S")
    sites.save_sites([d])
    assert bookmarks.save_site(d["id"], [Bookmark("Web", remote="/public_html")])
    assert bookmarks.load_site(d["id"])[0].remote == "/public_html"
    assert not bookmarks.save_site("nope", [])
    assert bookmarks.unique("Music", bookmarks.load_global()) == "Music (2)"


def test_add_global_and_site_bookmarks(qapp, window, ftp_server):
    from pr7f.bookmark_dialog import AddBookmarkDialog
    dlg = AddBookmarkDialog(window.local.path, "", "", window)          # not connected: global only
    assert dlg.globl.isChecked() and not dlg.site.isEnabled()
    dlg.form.name.setText("Local music")
    dlg.accept()
    assert [b.name for b in bookmarks.load_global()] == ["Local music"]
    sid = connect_site(qapp, window, ftp_server)
    window.navigate("/music")
    assert window.browser.wait_idle()
    dlg = AddBookmarkDialog(window.local.path, window.remote.path, window.site_id, window)
    assert dlg.site.isChecked() and dlg.form.remote.text() == "/music"  # site-specific when it can be
    dlg.form.name.setText("Music on the site")
    dlg.form.sync.setChecked(True)
    dlg.accept()
    assert bookmarks.load_site(sid) == [Bookmark("Music on the site", window.local.path, "/music", True, False)]
    stored = json.loads(open(os.path.join(sites.data_dir(), "sites.json"), encoding="utf-8").read())
    assert stored[0]["bookmarks"][0]["name"] == "Music on the site"     # kept with the site
    window._fill_bookmarks()
    names = [a.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
             for a in window.bookmarks_menu.actions() if a.text() and not a.isSeparator()]
    assert names == ["Add bookmark...", "Manage bookmarks...", "Local music", "Music on the site"]
    window.disconnect()
    assert window.browser.wait_idle()
    window._fill_bookmarks()
    names = [a.text().replace("&", "") for a in window.bookmarks_menu.actions() if a.text() and not a.isSeparator()]
    assert names == ["Add bookmark...", "Manage bookmarks...", "Local music"]  # the site's: only while connected
    bookmarks.save_global([Bookmark("Rock & Roll", remote="/r")])
    window._fill_bookmarks()
    assert window.bookmarks_menu.actions()[-1].text() == "Rock && Roll"  # shows as "Rock & Roll"


def test_open_bookmark_sync_and_compare(qapp, window, ftp_server, server_root):
    (server_root / "music" / "live").mkdir()
    connect_site(qapp, window, ftp_server)
    b = Bookmark("Music", str(window.local_dir / "music"), "/music", sync=True, compare=True)
    window.go_bookmark(b)
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music")
    assert window.local.path == str(window.local_dir / "music")
    assert window.toolbar.keys["sync"].isChecked() and window.toolbar.keys["compare"].isChecked()
    assert window.local.model.marks == {}                                # live on both sides; song only remote
    assert window.remote.model.marks == {"song.mp3": "only"}
    window.local.go(str(window.local_dir / "music" / "live"))           # synchronised: the remote side follows
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music/live")
    window.go_bookmark(Bookmark("Root", remote="/"))                     # a plain one switches them off
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/")
    assert not window.toolbar.keys["sync"].isChecked() and not window.toolbar.keys["compare"].isChecked()


def test_manage_bookmarks(qapp, window, ftp_server):
    from pr7f.bookmark_dialog import ManageBookmarksDialog
    bookmarks.save_global([Bookmark("A", remote="/a"), Bookmark("B", remote="/b")])
    sid = connect_site(qapp, window, ftp_server)
    dlg = ManageBookmarksDialog(sid, window)
    assert dlg.current == ("global", 0) and dlg.form.name.text() == "A"
    dlg.form.name.setText("A renamed")
    dlg.duplicate()                                                     # keeps the edit, copies it
    assert [b.name for b in dlg.lists["global"]] == ["A renamed", "B", "A renamed (copy)"]
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0).child(1))
    dlg.delete()
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(1))                   # the site group (not a bookmark)
    dlg.new()
    assert dlg.current == ("site", 0) and dlg.lists["site"][0].name == "New bookmark"
    dlg.form.remote.setText("/music")
    dlg.accept()
    assert [b.name for b in bookmarks.load_global()] == ["A renamed", "A renamed (copy)"]
    assert bookmarks.load_site(sid) == [Bookmark("New bookmark", "", "/music", False, False)]


def test_site_manager_keeps_a_sites_bookmarks(qapp, window):
    from pr7f.site_manager import SiteManager
    d = sites.new_site("S")
    sites.save_sites([d])
    bookmarks.save_site(d["id"], [Bookmark("Web", remote="/www")])
    sm = SiteManager(window, select=d["id"])
    sm.host.setText("example.org")
    sm.accept()
    assert bookmarks.load_site(d["id"]) == [Bookmark("Web", "", "/www", False, False)]
    assert sites.to_site(sites.load_sites()[0]).id == d["id"]
