"""Directory listing filters, quick search and remote search: what the lists show, what folder transfers leave out,
and what the search finds on a real server."""

import os
import time

import pytest

from pr7f import filters, remote
from pr7f.filters import Condition, Filter, filter_matches
from servers import PASSWORD, USER


@pytest.mark.parametrize("cond, name, size, want", [
    (Condition("name", "ends", ".tmp"), "x.TMP", 0, True),
    (Condition("name", "begins", "~$"), "~$report.docx", 0, True),
    (Condition("name", "is", "thumbs.db"), "Thumbs.db", 0, True),
    (Condition("name", "contains", "live"), "Portal (Live).flac", 0, True),
    (Condition("name", "not_contains", "live"), "Portal (Live).flac", 0, False),
    (Condition("name", "regex", r"^\d{2} "), "01 Portal.flac", 0, True),
    (Condition("size", "greater", "1 MB"), "big", 2_000_000, True),
    (Condition("size", "less", "200k"), "small", 100_000, True),
    (Condition("size", "equals", "100"), "x", 100, True),
    (Condition("size", "greater", "abc"), "x", 10**9, False),           # not a size: never matches
])
def test_conditions(cond, name, size, want):
    assert filter_matches(Filter("f", [cond]), name, size) is want


def test_match_rules_files_dirs_case_date_path():
    f = Filter("f", [Condition("name", "ends", ".mp3"), Condition("size", "greater", "1000")], "all")
    assert filter_matches(f, "a.mp3", 5000) and not filter_matches(f, "a.mp3", 10)
    f.match = "any"
    assert filter_matches(f, "a.flac", 5000)
    f.match = "none"
    assert filter_matches(f, "a.flac", 10) and not filter_matches(f, "a.mp3", 10)
    d = Filter("d", [Condition("name", "is", ".git")], "any", files=False, dirs=True, case=True)
    assert filter_matches(d, ".git", is_dir=True) and not filter_matches(d, ".git") and not filter_matches(
        d, ".GIT", is_dir=True)
    t = Filter("t", [Condition("date", "before", "2020-01-01")])
    assert filter_matches(t, "old", mtime=time.mktime((2019, 5, 1, 0, 0, 0, 0, 0, -1)))
    assert not filter_matches(t, "new", mtime=time.time())
    p = Filter("p", [Condition("path", "contains", "/cache/")])
    assert filter_matches(p, "x", path="/www/cache/x")


def test_defaults_and_storage():
    fs = filters.load()
    assert [f.name for f in fs.filters][:2] == ["Temporary and backup files", "Thumbs.db and desktop.ini"]
    assert not fs.local and not fs.remote                                # FileZilla starts with none on
    fs.local.add("Thumbs.db and desktop.ini")
    filters.save(fs)
    again = filters.load()
    assert again.hides("local", "Thumbs.db") and not again.hides("remote", "Thumbs.db")
    filters.save(filters.FilterSet(filters.load().filters))


# ------------------------------------------------------------------ in the window
def wait(qapp, cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from pr7f.main_window import MainWindow
    local = tmp_path / "local"
    (local / "Album").mkdir(parents=True)
    for name in ("01 Portal.flac", "Thumbs.db", "song.mp3.tmp", "notes.txt"):
        (local / name).write_bytes(b"x" * 10)
    (local / "Album" / "track.flac").write_bytes(b"y" * 10)
    (local / "Album" / "Thumbs.db").write_bytes(b"z")
    monkeypatch.setattr("pr7f.main_window.QMessageBox.question", lambda *a, **k: __import__(
        "PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
    w = MainWindow(str(local))
    w.answers = {"cert": lambda p: "once", "hostkey": lambda p: "once", "exists": lambda ex: ("overwrite", False),
                 "no_open": True}
    w.local_dir = local
    w.show()
    yield w
    w.set_filters(filters.FilterSet(filters.load().filters))
    w.close()


def shown(model):
    return sorted(r.name for r in model.rows if r.kind not in ("up", "drive"))


def connect(qapp, w, port, host="127.0.0.1"):
    w.qc["host"].setText(host)
    w.qc["user"].setText(USER)
    w.qc["password"].setText(PASSWORD)
    w.qc["port"].setText(str(port))
    w.quickconnect()
    assert w.browser.wait_idle() and wait(qapp, lambda: w.remote.path == "/")


def test_filters_dialog_hides_per_side(qapp, window, ftp_server, server_root):
    (server_root / "Thumbs.db").write_bytes(b"x")
    connect(qapp, window, ftp_server.port)
    from pr7f.filter_dialog import FiltersDialog
    dlg = FiltersDialog(window.filters, window)
    dlg.set_on("Thumbs.db and desktop.ini", local=True, remote_on=False)
    dlg.set_on("Temporary and backup files", local=True, remote_on=True)
    window.set_filters(dlg.result())
    assert shown(window.local.model) == ["01 Portal.flac", "Album", "notes.txt"]
    assert "(filtered)" in window.local.info.text()
    assert "Thumbs.db" in shown(window.remote.model)                    # off for the remote side
    assert window.toolbar.keys["filter"].isChecked()                     # the funnel key lit
    assert filters.load().local == {"Thumbs.db and desktop.ini", "Temporary and backup files"}  # kept
    window.set_filters(filters.FilterSet(window.filters.filters))
    assert "Thumbs.db" in shown(window.local.model) and not window.toolbar.keys["filter"].isChecked()


def test_filter_editor(qapp, window):
    from pr7f.filter_dialog import FilterEditor, FiltersDialog
    dlg = FiltersDialog(window.filters, window)
    ed = FilterEditor(dlg.fs, dlg)
    ed.new("No FLAC")
    ed.conds.set_conditions([Condition("name", "ends", ".flac")])
    ed.files.setChecked(True)
    ed.dirs.setChecked(False)
    ed.list.setCurrentRow(0)                                             # moving away keeps the edits
    ed.list.setCurrentRow(len(ed.filters) - 1)
    assert ed.conds.conditions() == [Condition("name", "ends", ".flac")]
    ed.rename("FLAC files")
    dlg.apply_edit(ed)
    dlg.set_on("FLAC files", local=True)
    window.set_filters(dlg.result())
    assert shown(window.local.model) == ["Album", "Thumbs.db", "notes.txt", "song.mp3.tmp"]
    assert any(f.name == "FLAC files" for f in filters.load().filters)


def test_quick_search(qapp, window):
    window.quick_search()
    assert window.local.quick.isVisible()
    window.local.quick.edit.setText("portal")
    assert shown(window.local.model) == ["01 Portal.flac"]
    window.local.quick.edit.setText("*.t?t")
    assert shown(window.local.model) == ["notes.txt"]
    window.local.quick.close_search()
    assert len(shown(window.local.model)) == 5


def test_folder_transfers_leave_filtered_files_out(qapp, window, ftp_server, server_root):
    connect(qapp, window, ftp_server.port)
    fs = filters.FilterSet(window.filters.filters, {"Thumbs.db and desktop.ini"}, set())
    window.set_filters(fs)
    window._dropped_remote("local", ["Album"], "")
    assert wait(qapp, lambda: (server_root / "Album" / "track.flac").exists() and not window.queue.snapshot()["queued"])
    assert sorted(os.listdir(server_root / "Album")) == ["track.flac"]   # Thumbs.db stayed home


def test_search_remote(qapp, window, sftp_server, server_root):
    (server_root / "music" / "live").mkdir()
    (server_root / "music" / "live" / "Portal (Live).flac").write_bytes(b"x" * 5000)
    (server_root / "music" / "Portal.flac").write_bytes(b"x" * 10)
    (server_root / "backup.bak").write_bytes(b"x")
    connect(qapp, window, sftp_server.port, host="sftp://127.0.0.1")
    from pr7f.filter_dialog import SearchDialog
    dlg = SearchDialog(window)
    dlg.conds.set_conditions([Condition("name", "contains", "portal")])
    dlg.toggle()
    dlg.wait()
    assert sorted(p for p, _ in dlg.model.rows) == ["/music/Portal.flac", "/music/live/Portal (Live).flac"]
    assert dlg.status.text().startswith("2 found in 3 folder(s)")
    dlg.conds.set_conditions([Condition("name", "contains", "portal"), Condition("size", "greater", "1000")])
    dlg.toggle()
    dlg.wait()
    assert [p for p, _ in dlg.model.rows] == ["/music/live/Portal (Live).flac"]
    dlg.download(dlg.model.rows)                                          # into the local folder
    assert wait(qapp, lambda: (window.local_dir / "Portal (Live).flac").exists() and
                not window.queue.snapshot()["queued"])
    dlg.go_to("/music/live/Portal (Live).flac")
    assert window.browser.wait_idle() and wait(qapp, lambda: window.remote.path == "/music/live")
    dlg.delete(list(dlg.model.rows), confirm=False)
    assert window.browser.wait_idle() and not (server_root / "music" / "live" / "Portal (Live).flac").exists()
    assert dlg.model.rows == []


def test_search_engine_skips_unreadable_and_stops(ftp_server, server_root):
    from pr7f.search import search
    (server_root / "a").mkdir()
    (server_root / "a" / "x.txt").write_bytes(b"1")
    sess = remote.open_session(remote.Site("127.0.0.1", USER, PASSWORD, ftp_server.port))
    found, errors = [], []
    crit = Filter("s", [Condition("name", "ends", ".txt")])
    n = search(sess, "/", crit, lambda p, e: found.append(p), log=lambda k, t: errors.append(t))
    assert found == ["/a/x.txt"] and n == 3
    assert search(sess, "/", crit, lambda p, e: found.append(p), cancelled=lambda: True) == 0
    sess.list = lambda path: (_ for _ in ()).throw(remote.RemoteError("550 Permission denied")) if path == "/a" \
        else remote.FTPSession.list(sess, path)
    found.clear()
    search(sess, "/", crit, lambda p, e: found.append(p), log=lambda k, t: errors.append(t))
    assert found == [] and errors == ["/a: 550 Permission denied"]
    sess.close()
