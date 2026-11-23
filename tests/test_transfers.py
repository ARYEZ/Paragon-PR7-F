"""The transfer queue against real servers: folders both ways, several workers, the file-exists answers,
resume, cancel and retry."""

import os
import time

import pytest

from pr7f import remote
from pr7f.transfers import Item, TransferQueue
from servers import PASSWORD, USER


def make_queue(kind, ftp_server, sftp_server, **kw):
    if kind == "sftp":
        site = remote.Site("127.0.0.1", USER, PASSWORD, sftp_server.port, "sftp")
        connect = lambda: remote.open_session(site, host_key_check=lambda *a: "once")  # noqa: E731
    else:
        site = remote.Site("127.0.0.1", USER, PASSWORD, ftp_server.port)
        connect = lambda: remote.open_session(site)  # noqa: E731
    return TransferQueue(connect, **kw)


@pytest.fixture(params=["ftp", "sftp"])
def kind(request):
    return request.param


def tree(path):
    out = {}
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, path).replace(os.sep, "/")] = open(p, "rb").read()
    return out


def run(q):
    q.start()
    assert q.wait(60)


def test_upload_and_download_folders(kind, ftp_server, sftp_server, server_root, tmp_path):
    album = tmp_path / "ELSEWORLD"
    (album / "art").mkdir(parents=True)
    for name, n in (("01 Portal.flac", 200_000), ("02 Ruins.flac", 150_000), ("art/front.jpg", 50_000)):
        (album / name).write_bytes(os.urandom(n))
    q = make_queue(kind, ftp_server, sftp_server, workers=2)
    q.upload(str(album), "/ELSEWORLD")
    run(q)
    assert tree(server_root / "ELSEWORLD") == tree(album)
    snap = q.snapshot()
    assert not snap["failed"] and not snap["queued"] and len(snap["done"]) == 5  # 2 folders + 3 files
    back = tmp_path / "back"
    q2 = make_queue(kind, ftp_server, sftp_server)
    q2.download("/ELSEWORLD", str(back / "ELSEWORLD"), remote.Entry("ELSEWORLD", is_dir=True))
    run(q2)
    assert tree(back / "ELSEWORLD") == tree(album)


def test_file_exists_answers(kind, ftp_server, sftp_server, server_root, tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_bytes(b"new content")
        (server_root / name).write_bytes(b"old")
    asked = []

    def ask(ex):
        asked.append((ex.item.remote, ex.source_size, ex.target_size))
        return {"/a.txt": ("skip", False), "/b.txt": ("rename", "b (2).txt"), "/c.txt": ("overwrite", True)}[
            ex.item.remote]
    q = make_queue(kind, ftp_server, sftp_server, workers=1, ask_exists=ask)
    for name in ("a.txt", "b.txt", "c.txt"):
        q.upload(str(tmp_path / name), f"/{name}")
    run(q)
    assert [a[0] for a in asked] == ["/a.txt", "/b.txt", "/c.txt"] and asked[0][1:] == (11, 3)
    assert (server_root / "a.txt").read_bytes() == b"old"                       # skipped
    assert (server_root / "b.txt").read_bytes() == b"old"
    assert (server_root / "b (2).txt").read_bytes() == b"new content"           # renamed
    assert (server_root / "c.txt").read_bytes() == b"new content"
    assert [i.status for i in q.snapshot()["done"]].count("skipped") == 1


def test_apply_to_all_and_if_newer(kind, ftp_server, sftp_server, server_root, tmp_path):
    for name in ("x.txt", "y.txt"):
        (tmp_path / name).write_bytes(b"local")
        (server_root / name).write_bytes(b"server")
    os.utime(tmp_path / "x.txt", (1_000_000_000, 1_000_000_000))                # older than the server's
    os.utime(server_root / "y.txt", (1_000_000_000, 1_000_000_000))             # the server's y is the old one
    asked = []
    q = make_queue(kind, ftp_server, sftp_server, workers=1,
                   ask_exists=lambda ex: asked.append(1) or ("overwrite_newer", True))
    q.upload(str(tmp_path / "x.txt"), "/x.txt")
    q.upload(str(tmp_path / "y.txt"), "/y.txt")
    run(q)
    assert asked == [1]                                                          # asked once, for all
    assert (server_root / "x.txt").read_bytes() == b"server"                    # not newer: kept
    assert (server_root / "y.txt").read_bytes() == b"local"                     # newer: overwritten


def test_resume_download(kind, ftp_server, sftp_server, server_root, tmp_path):
    full = (server_root / "music" / "song.mp3").read_bytes()
    local = tmp_path / "song.mp3"
    local.write_bytes(full[:100_000])
    q = make_queue(kind, ftp_server, sftp_server, ask_exists=lambda ex: ("resume", False))
    q.download("/music/song.mp3", str(local), remote.Entry("song.mp3", size=len(full)))
    run(q)
    assert local.read_bytes() == full


def test_failures_and_retry(kind, ftp_server, sftp_server, server_root, tmp_path):
    q = make_queue(kind, ftp_server, sftp_server)
    q.download("/missing.bin", str(tmp_path / "missing.bin"), remote.Entry("missing.bin", size=5))
    run(q)
    failed = q.snapshot()["failed"]
    assert len(failed) == 1 and failed[0].error
    (server_root / "missing.bin").write_bytes(b"12345")
    q.retry_failed()
    run(q)
    assert (tmp_path / "missing.bin").read_bytes() == b"12345" and not q.snapshot()["failed"]


def test_cannot_connect_fails_after_retries(tmp_path):
    tries = []

    def connect():
        tries.append(1)
        raise remote.RemoteError("Could not connect to 127.0.0.1:1: refused")
    q = TransferQueue(connect)
    (tmp_path / "f").write_bytes(b"x")
    q.upload(str(tmp_path / "f"), "/f")
    run(q)
    assert len(tries) == 3 and q.snapshot()["failed"][0].error.startswith("Could not connect")


def test_stop_puts_the_running_transfer_back(kind, ftp_server, sftp_server, server_root, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(30_000_000))
    q = make_queue(kind, ftp_server, sftp_server)
    q.upload(str(big), "/big.bin")
    q.start()
    for _ in range(400):
        if q.items[0].transferred > 0:
            break
        time.sleep(0.01)
    q.stop()
    assert q.wait(30)
    assert q.items[0].status == "queued"                                        # back in the queue, not failed
    q.default_action["upload"] = "overwrite"
    run(q)
    assert (server_root / "big.bin").read_bytes() == big.read_bytes()
