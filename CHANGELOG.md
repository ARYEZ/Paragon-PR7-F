# Changelog

## 0.7.1

- The family's list knows the newest apps (PR7-HB, PR7-FS, PR7-AR, PR7-WM), so links between apps and Check for Updates find them.

## 0.7.0

- **One finish for the whole family.** Choosing OBSIDIAN or AURORA here switches every Paragon app, open ones included (within a couple of seconds), and every app starts in the family's choice.
- In AURORA, group titles and selected rows are dark and readable (they were white on the light finish).

## 0.6.1

- Knows the whole family: PR7-DU, PR7-CB, PR7-IS, PR7-PM and PR7-SM are in its list of family apps (their permanent install IDs), so the family links find them when they're installed.

## 0.6.0

- **Check for Updates knows PR7-U**, the family installer. When it's installed, the update window has **Update All in PR7-U**, and a check by hand that finds PR7-F up to date offers to open PR7-U for the rest of the family.

## 0.5.0

- **Check for updates**: a few seconds after starting (at most once a day) PR7-F asks GitHub whether a newer release is out; if so, a note offers What's new, Install Now (downloads with progress, installs over this copy, and PR7-F reopens), Later or Skip This Version. "Help > Check for updates" checks by hand. Only the app's name is sent.
- **Open in PR7-E** on the local side's right-click menu, when PR7-E is installed.

## 0.4.0

- **Connection tabs**, as FileZilla's: File > New tab (Ctrl+T) and Close tab (Ctrl+W, or the tab's ×). Each tab has
  its own connection, local and remote folders, message log, synchronised browsing and comparison; the tab is named
  after its site (or user@host). The last tab stays open: closing it disconnects.
- Connecting while the tab is already connected asks, as FileZilla does: **connect in a new tab** or **abort the
  previous connection**, with "Always perform this action" (Edit > Settings changes it later).
- One queue list for every tab, with a **Server** column; Process queue / Retry / Clear act on all of them. Closing a
  tab with files still queued asks first.

## 0.3.1

- Windows Defender could block PR7-F.exe as "potentially unwanted software" (a false positive common to PyInstaller
  programs). The build now uses a PyInstaller starter compiled for PR7-F instead of the shared prebuilt one, the .exe
  carries proper file details (product, company, version), nothing is UPX-packed, and CI scans the program and the
  installer with Defender before publishing them.

## 0.3.0

- **Bookmarks**, as FileZilla's: Add bookmark (Ctrl+B) and Manage bookmarks (Ctrl+Shift+B); each has a name, a local
  directory and/or a remote directory, and can turn on synchronised browsing and directory comparison when opened.
  Global bookmarks are always in the Bookmarks menu; site-specific ones are kept with their Site Manager site and
  listed while connected to it. Names with "&" show as written.

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
