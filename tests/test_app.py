"""The command line: --check (what CI runs against the installed program) and --version."""

import json

from pr7f import app
from servers import PASSWORD, USER


def test_check_against_both_protocols(ftp_server, sftp_server, tmp_path):
    out = tmp_path / "out.json"
    scheme = "ftpes" if ftp_server.kind == "tls" else "ftp"
    assert app.check(f"{scheme}://{USER}:{PASSWORD}@127.0.0.1:{ftp_server.port}", str(out)) == 0
    assert json.loads(out.read_text()) == {"encrypted": ftp_server.kind == "tls", "names": ["index.html", "music"]}
    assert app.check(f"sftp://{USER}:{PASSWORD}@127.0.0.1:{sftp_server.port}", str(out)) == 0
    assert json.loads(out.read_text())["encrypted"] is True
    assert app.check(f"ftp://{USER}:wrong@127.0.0.1:{ftp_server.port}", str(out)) == 1
    assert "Login" in json.loads(out.read_text())["error"]


def test_version(capsys):
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == "0.1.0"
