"""Search remote files (Server > Search remote files, F3), as FileZilla's: from a folder, through every folder
inside it, the entries matching the conditions. (No Qt here: the dialog runs it on a thread.)"""

from __future__ import annotations

from . import remote
from .filters import Filter, filter_matches


def search(sess, start: str, criteria: Filter, found, progress=None, cancelled=None, log=None) -> int:
    """Walk `start` and its subfolders on `sess`; call found(path, entry) for each match, progress(folder) per
    folder. Folders that can't be listed are reported and skipped; links to folders aren't followed (they can
    loop). Returns how many folders were searched."""
    stack = [start or "/"]
    seen = set()
    folders = 0
    while stack:
        if cancelled and cancelled():
            break
        folder = stack.pop()
        if folder in seen:
            continue
        seen.add(folder)
        if progress:
            progress(folder)
        try:
            entries = sess.list(folder)
        except remote.RemoteError as e:
            if log:
                log("Error", f"{folder}: {e}")
            continue
        folders += 1
        subdirs = []
        for e in sorted(entries, key=lambda e: e.name.lower()):
            path = remote.join(folder, e.name)
            if filter_matches(criteria, e.name, e.size, e.mtime, e.is_dir, path, e.perms):
                found(path, e)
            if e.is_dir and not e.is_link:
                subdirs.append(path)
        stack.extend(reversed(subdirs))  # depth first, in name order
    return folders
