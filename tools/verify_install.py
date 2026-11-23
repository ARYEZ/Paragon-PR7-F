"""Check a real install of PR7-F-Setup.exe (CI, Windows): python tools/verify_install.py installed|uninstalled

`installed` starts real FTP, FTPS and SFTP servers here and has the installed PR7-F.exe connect to each (--check),
so the frozen program is shown to carry TLS, paramiko and cryptography."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from servers import PASSWORD, USER, FTPServer, SFTPServerThread  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-F"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-F.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{34F163CD-E4F2-4415-9865-1175C28F5408}_is1"


def value(path, name=""):
    try:
        k = winreg.OpenKey(HKCU, path)
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(k)


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-F.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7f" / "fonts" / "Inter-Regular.ttf",
              APP / "_internal" / "pr7f" / "icons" / "app.ico"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(UNINSTALL, "DisplayName") == "Paragon PR7-F", "Installed apps entry", p)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "server"
        (root / "music").mkdir(parents=True)
        (root / "index.html").write_bytes(b"hi")
        ftp, ftps = FTPServer(str(root), False, d), FTPServer(str(root), True, d)
        sftp = SFTPServerThread(str(root))
        try:
            for name, url, enc in (("FTP", f"ftp://{USER}:{PASSWORD}@127.0.0.1:{ftp.port}", False),
                                   ("FTP over TLS", f"ftpes://{USER}:{PASSWORD}@127.0.0.1:{ftps.port}", True),
                                   ("SFTP", f"sftp://{USER}:{PASSWORD}@127.0.0.1:{sftp.port}", True)):
                out = Path(d) / f"{name}.json"
                subprocess.run([str(exe), "--check", url, str(out)], timeout=120, check=False)
                got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
                check(got.get("names") == ["index.html", "music"] and got.get("encrypted") is enc,
                      f"PR7-F.exe connects over {name} ({got})", p)
        finally:
            ftp.stop()
            ftps.stop()
            sftp.stop()
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-F.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
