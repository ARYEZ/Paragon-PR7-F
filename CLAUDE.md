# Paragon PR7-F: notes for Claude

**Paragon PR7-F** is the owner's personal file transfer program: Python (**PySide6** + **paramiko**, `ftplib`) that
**works the way FileZilla works**, in the Paragon family look (the PR7 plugins, Paragon Photo, PR7-Z
`ARYEZ/Paragon-PR7-Z`, PR7-W `ARYEZ/Paragon-PR7-W`, PR7-L `ARYEZ/Paragon-PR7-L`). Windows 10/11 x64 is the target;
it runs on Linux for tests. The owner writes Python; explain the why of changes.

## How it's built

- `pr7f/remote.py` (no Qt): `Site` (the Site Manager's General tab), `parse_quick` (the quick-connect bar's rules:
  port 22 / sftp:// -> SFTP, ftps:// implicit, ftpes:// explicit), `FTPSession` (ftplib; explicit TLS if available is
  the default, `_FTP_TLS.ntransfercmd` reuses the TLS session on data connections, MLSD when FEAT has MLST/MLSD else
  LIST parsed by `parse_list_line`), `SFTPSession` (paramiko; known_hosts in the data folder; `host_key_check`).
  Same methods on both; everything logged as Status/Command/Response/Error, `PASS ********`.
- `pr7f/transfers.py` (no Qt): `TransferQueue` with worker threads, each opening its own session; folders expanded
  in place; `ask_exists(Exists) -> (action, apply_to_all)` or `("rename", name)`; retries on lost connections;
  `stop()` puts running items back.
- `pr7f/sites.py` (no Qt): sites JSON in `%APPDATA%\Paragon\PR7-F` (`PR7F_DATA` overrides), passwords only via
  `keyring` (Windows Credential Manager); `PR7F_MEMORY_KEYRING` = an in-memory store (tests). Recent servers never
  hold passwords. Trusted FTPS certificates by SHA-256.
- `pr7f/browser.py`: `Browser` runs the remote pane's commands one at a time on a thread; `Asker` lets any thread ask
  the GUI (host key, certificate, file exists). `pr7f/panes.py`: list models are plain Python lists (never
  QStandardItemModel: PR7-Z's crash), the family selection band, drag and drop. `pr7f/main_window.py` wires it;
  `window.answers` replaces dialogs in tests.
- Installer `installer/pr7f.iss` (Inno Setup 6, per user, AppId {34F163CD-E4F2-4415-9865-1175C28F5408} permanent).
  CI installs it, and `tools/verify_install.py installed` starts real FTP/FTPS/SFTP servers and runs the installed
  `PR7-F.exe --check URL OUT` against each.

## The look (family rules)

- Theme is PR7-L's (OBSIDIAN + AURORA); colours the family's only; Inter; labels UPPER CASE. The PR7-F mark: PR7
  `Logo.cpp` geometry plus an F (`widgets.F_SHAPE`); icon by `tools/make_icon.py`, wizard art by
  `tools/make_installer_art.py`. Check visuals with `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT`.

## Rules

- Behaviour questions: do what FileZilla does (defaults, menus, the file-exists choices, shortcuts).
- Tests: `python -m pytest` (offscreen) against real servers from `tests/servers.py` (pyftpdlib single-threaded
  server: its threaded one loses the reply to a wrong password; paramiko's server side for SFTP). Never the real
  data folder or Credential Manager (conftest sets `PR7F_DATA` and `PR7F_MEMORY_KEYRING`).
- Releases: bump `__version__` in `pr7f/__init__.py`, add a `## x.y.z` section to CHANGELOG.md; a `v*` tag publishes.
