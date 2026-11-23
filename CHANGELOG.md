# Changelog

## 0.2.0

- **Directory listing filters** (View, Ctrl+I, the funnel key), as FileZilla's: filters with conditions on the
  filename (contains, is, begins/ends with, regex, does not contain), size (1.5 MB, 200 KB ...), date, path and
  permissions; all / any / none must match; files, folders, case. Each is switched on separately for the local and
  the remote side, and they also leave filtered files out of folder transfers. FileZilla's starting set: temporary
  and backup files, Thumbs.db and desktop.ini, CVS/SVN and Git folders, hidden files, configuration files. The list's
  summary says "(filtered)" and the funnel key lights up while one is on.
- **Quick search** (Ctrl+F): a box under the list in use; text or a wildcard pattern (*.mp3).
- **Search remote files** (F3, the magnifier key): from a folder through all its subfolders, on its own connection,
  with the same conditions; Stop; results can be downloaded, deleted, or shown in the remote pane.

## 0.1.0

First version.

- Connections (remote.py): FTP with explicit TLS if available (FileZilla's default), required or implicit TLS, plain
  FTP; passive mode, MLSD or LIST (Unix and Windows formats), TLS session reuse on data connections; SFTP with
  password or key file and known-hosts checking. Every command and reply in the message log (passwords hidden).
- Transfer queue: workers with their own connections, folders both ways, the file-exists question, resume, retries,
  stop and continue, retry failed.
- The window: quick-connect with history, message log, local and remote panes with trees, drag and drop, context
  menus, View/Edit, directory comparison, synchronised browsing, status bar with the encryption.
- Site Manager with passwords in Windows Credential Manager; Settings (simultaneous transfers, finish).
- Per-user installer; CI tests against real FTP/FTPS/SFTP servers and checks the installed program connects.
