# Changelog

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
