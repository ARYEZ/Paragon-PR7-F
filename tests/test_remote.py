"""The connection engine against real FTP, FTPS (explicit TLS) and SFTP servers on this machine: logins,
listings, transfers checked byte for byte, resume, and the file operations."""

import os
from datetime import datetime, timezone

import pytest

from pr7f import remote
from pr7f.remote import Site, parse_list_line, parse_quick
from servers import PASSWORD, USER


def ftp_site(server, encryption="auto", **kw):
    return Site("127.0.0.1", USER, PASSWORD, server.port, "ftp", encryption, **kw)


def sftp_site(server, **kw):
    return Site("127.0.0.1", USER, PASSWORD, server.port, "sftp", **kw)


def trust(*a):
    return "once"


def connect(kind, server, log=None, **kw):
    if kind == "sftp":
        return remote.open_session(sftp_site(server, **kw), log, host_key_check=trust)
    return remote.open_session(ftp_site(server, **kw), log)


@pytest.fixture(params=["ftp", "sftp"])
def session(request, ftp_server, sftp_server):
    s = connect(request.param, ftp_server if request.param == "ftp" else sftp_server)
    yield s
    s.close()


# ------------------------------------------------------------------ the quick-connect bar
@pytest.mark.parametrize("host, port, want", [
    ("ftp.example.com", "", ("ftp", "auto", 21, "ftp.example.com")),
    ("ftp.example.com", "22", ("sftp", "auto", 22, "ftp.example.com")),        # port 22: SFTP, as FileZilla
    ("sftp://nas.local", "", ("sftp", "auto", 22, "nas.local")),
    ("ftps://secure.example.com", "", ("ftp", "implicit", 990, "secure.example.com")),
    ("ftpes://x.example.com:2121", "", ("ftp", "explicit", 2121, "x.example.com")),
    ("bob:pw@host.example:2222/some/dir", "", ("ftp", "auto", 2222, "host.example")),
    ("[2001:db8::1]:21", "", ("ftp", "auto", 21, "2001:db8::1")),
])
def test_quickconnect(host, port, want):
    s = parse_quick(host, "", "", port)
    assert (s.protocol, s.encryption, s.real_port, s.host) == want


def test_quickconnect_user_and_anonymous():
    assert parse_quick("bob:pw@h").user == "bob" and parse_quick("bob:pw@h").password == "pw"
    assert parse_quick("h").user == "anonymous" and parse_quick("h").logon == "anonymous"
    with pytest.raises(remote.RemoteError):
        parse_quick("  ")


# ------------------------------------------------------------------ FTP specifics
def test_ftp_uses_tls_when_offered_and_logs_it(ftp_server):
    log = []
    s = connect("ftp", ftp_server, lambda k, t: log.append((k, t)))
    assert s.encrypted is (ftp_server.kind == "tls")
    text = [t for _, t in log]
    assert ("Command", "AUTH TLS") in log
    if ftp_server.kind == "tls":
        assert any(t.startswith("TLS connection established") for t in text)
        assert ("Command", "PROT P") in log
    else:
        assert "Insecure server, it does not support FTP over TLS." in text
    assert ("Command", "PASS ********") in log and not any(PASSWORD in t for t in text)  # never the password
    assert ("Response", "220 Paragon test FTP server ready.") in log and text.count("220 Paragon test FTP server ready.") == 1
    s.close()


def test_ftp_tls_required(ftp_server):
    if ftp_server.kind == "tls":
        connect("ftp", ftp_server, encryption="explicit").close()
    else:
        with pytest.raises(remote.RemoteError, match="requires it"):
            connect("ftp", ftp_server, encryption="explicit")


def test_ftp_wrong_password_and_no_server(ftp_server):
    with pytest.raises(remote.RemoteError, match="Login refused"):
        remote.open_session(Site("127.0.0.1", USER, "wrong", ftp_server.port))
    with pytest.raises(remote.RemoteError, match="Could not connect"):
        remote.open_session(Site("127.0.0.1", USER, PASSWORD, 1, timeout=2))


def test_ftp_listing_without_mlsd(ftp_server):
    s = connect("ftp", ftp_server)
    s.features -= {"MLSD", "MLST"}  # an old server: LIST, parsed
    names = {e.name: e for e in s.list("/")}
    assert names["music"].is_dir and names["index.html"].size == 15 and names["index.html"].perms.startswith("-rw")
    assert names["index.html"].owner  # LIST gives owner and group
    s.close()


@pytest.mark.parametrize("line, want", [
    ("-rw-r--r--   1 paragon  www     4207 Nov 21 10:03 index.html", ("index.html", 4207, False, "paragon www")),
    ("drwxr-xr-x   2 paragon  www     4096 Mar  8  2019 old stuff", ("old stuff", 4096, True, "paragon www")),
    ("lrwxrwxrwx   1 root root  7 Jan  1 2020 latest -> v2", ("latest", 7, False, "root root")),
    ("11-21-26  10:03AM                 4207 index.html", ("index.html", 4207, False, "")),
    ("03-08-19  09:15PM       <DIR>          My Music", ("My Music", 0, True, "")),
])
def test_list_line_formats(line, want):
    e = parse_list_line(line, now=datetime(2026, 11, 23, tzinfo=timezone.utc))
    assert (e.name, e.size, e.is_dir, e.owner) == want and e.mtime > 0
    assert parse_list_line("total 12") is None


def test_list_year_rollover():
    e = parse_list_line("-rw-r--r-- 1 a b 1 Dec 30 23:59 x", now=datetime(2027, 1, 2, tzinfo=timezone.utc))
    assert datetime.fromtimestamp(e.mtime, timezone.utc).year == 2026


# ------------------------------------------------------------------ both protocols
def test_listing(session):
    assert session.pwd() == "/"
    got = {e.name: e for e in session.list("/")}
    assert set(got) == {"music", "index.html"}
    assert got["music"].is_dir and not got["index.html"].is_dir and got["index.html"].size == 15
    assert got["index.html"].mtime > 1_600_000_000
    assert [e.name for e in session.list("/music")] == ["song.mp3"]


def test_download_upload_byte_exact(session, server_root, tmp_path):
    local = tmp_path / "down.mp3"
    seen = []
    session.download("/music/song.mp3", str(local), progress=seen.append)
    assert local.read_bytes() == (server_root / "music" / "song.mp3").read_bytes() and sum(seen) == 300_000
    data = os.urandom(1_000_001)
    up = tmp_path / "up.bin"
    up.write_bytes(data)
    session.upload(str(up), "/music/up ü.bin")
    assert (server_root / "music" / "up ü.bin").read_bytes() == data  # non-ASCII names too
    assert session.size("/music/up ü.bin") == len(data)


def test_resume_both_ways(session, server_root, tmp_path):
    full = (server_root / "music" / "song.mp3").read_bytes()
    part = tmp_path / "part.mp3"
    part.write_bytes(full[:123_456])
    session.download("/music/song.mp3", str(part), offset=123_456)
    assert part.read_bytes() == full
    data = os.urandom(500_000)
    src = tmp_path / "big.bin"
    src.write_bytes(data)
    (server_root / "big.bin").write_bytes(data[:200_000])  # an upload that broke off
    session.upload(str(src), "/big.bin", offset=200_000)
    assert (server_root / "big.bin").read_bytes() == data


def test_cancel(session, tmp_path):
    with pytest.raises(remote.RemoteError, match="Cancelled"):
        session.download("/music/song.mp3", str(tmp_path / "x"), cancelled=lambda: True)


def test_file_operations(session, server_root):
    session.mkdir("/new folder")
    assert (server_root / "new folder").is_dir()
    session.rename("/index.html", "/new folder/home.html")
    assert (server_root / "new folder" / "home.html").read_bytes() == b"<html>hi</html>"
    session.chmod("/new folder/home.html", 0o600)
    if os.name != "nt":
        assert (server_root / "new folder" / "home.html").stat().st_mode & 0o777 == 0o600
    session.delete("/new folder/home.html")
    session.rmdir("/new folder")
    assert sorted(os.listdir(server_root)) == ["music"]
    with pytest.raises(remote.RemoteError):
        session.delete("/nothing.txt")


# ------------------------------------------------------------------ SFTP specifics
def test_sftp_host_key_asked_and_remembered(sftp_server, tmp_path):
    known = str(tmp_path / "known_hosts")
    asked = []

    def check(host, port, kind, fp, changed):
        asked.append((host, port, kind, fp.startswith("SHA256:"), changed))
        return "always"
    s = remote.open_session(sftp_site(sftp_server), host_key_check=check, known_hosts=known)
    s.close()
    assert asked == [("127.0.0.1", sftp_server.port, "ecdsa-sha2-nistp256", True, False)]
    remote.open_session(sftp_site(sftp_server), host_key_check=check, known_hosts=known).close()
    assert len(asked) == 1                                         # trusted always: not asked again
    with pytest.raises(remote.HostKeyRejected):
        remote.open_session(sftp_site(sftp_server), host_key_check=lambda *a: None, known_hosts=str(tmp_path / "x"))


def test_sftp_changed_key_is_flagged(sftp_server, tmp_path):
    known = tmp_path / "known_hosts"
    known.write_text(f"[127.0.0.1]:{sftp_server.port} ecdsa-sha2-nistp256 AAAAold\n")
    flags = []
    remote.open_session(sftp_site(sftp_server), host_key_check=lambda *a: flags.append(a[4]) or "once",
                        known_hosts=str(known)).close()
    assert flags == [True]


def test_sftp_password_and_key_logins(server_root, tmp_path):
    import paramiko
    from servers import SFTPServerThread
    key = paramiko.ECDSAKey.generate()
    path = tmp_path / "id_ecdsa"
    key.write_private_key_file(str(path))
    srv = SFTPServerThread(str(server_root), pubkey=key)
    try:
        s = remote.open_session(Site("127.0.0.1", USER, "", srv.port, "sftp", logon="key", key_file=str(path)),
                                host_key_check=trust)
        assert "music" in [e.name for e in s.list("/")]
        s.close()
        with pytest.raises(remote.RemoteError, match="Authentication failed"):
            remote.open_session(Site("127.0.0.1", USER, "nope", srv.port, "sftp"), host_key_check=trust)
        (tmp_path / "k.ppk").write_bytes(b"PuTTY-User-Key-File-3: ssh-ed25519\n")
        with pytest.raises(remote.RemoteError, match="PuTTY"):
            remote.open_session(Site("127.0.0.1", USER, "", srv.port, "sftp", logon="key",
                                     key_file=str(tmp_path / "k.ppk")), host_key_check=trust)
    finally:
        srv.stop()


def test_entry_mode():
    assert remote.Entry("x", perms="-rw-r--r--").mode == 0o644
    assert remote.Entry("d", perms="drwxr-x---").mode == 0o750
    assert remote.Entry("y").mode is None
