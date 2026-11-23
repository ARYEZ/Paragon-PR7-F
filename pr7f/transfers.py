"""The transfer queue, as FileZilla's: files and folders go in, workers (2 at once by default, each with its own
connection) take them in order, folders are expanded as they're reached, and a file that's already there asks the
"Target file already exists" question (or uses the answer given for all). No Qt here: the window watches it through
`on_change` and answers `ask_exists` from its dialog.
"""

from __future__ import annotations

import itertools
import os
import posixpath
import threading
import time
from dataclasses import dataclass, field

from . import remote

ACTIONS = {"overwrite": "Overwrite", "overwrite_newer": "Overwrite if source newer",
           "overwrite_size": "Overwrite if different size", "overwrite_size_newer": "Overwrite if different size or "
           "source newer", "resume": "Resume", "rename": "Rename", "skip": "Skip"}
RETRIES = 2  # FileZilla's default: a transfer that loses its connection is tried twice more


@dataclass
class Item:
    direction: str                    # "upload" or "download"
    local: str
    remote: str
    size: int = 0
    is_dir: bool = False
    mtime: float = 0.0                # the source's modification time (for "if newer")
    status: str = "queued"            # queued, active, done, failed, skipped
    transferred: int = 0
    error: str = ""
    tries: int = 0
    id: int = field(default_factory=lambda: next(_ids))
    started: float = 0.0

    @property
    def speed(self) -> float:
        took = time.monotonic() - self.started if self.started else 0
        return self.transferred / took if took > 0.2 else 0.0


_ids = itertools.count(1)


@dataclass
class Exists:
    """What the question shows: both files' size and time."""
    item: Item
    source_size: int
    source_mtime: float
    target_size: int
    target_mtime: float


class TransferQueue:
    def __init__(self, connect, workers: int = 2, ask_exists=None, on_change=None, log=None, exclude=None):
        """connect() -> a connected remote session (a new one per worker). ask_exists(Exists) -> (action, apply_to_all)
        or (\"rename\", new name); None asks nothing and overwrites."""
        self.connect = connect
        self.workers = max(1, workers)
        self.ask_exists = ask_exists
        self.on_change = on_change or (lambda item: None)
        self.log = log or (lambda kind, text: None)
        # exclude(item) -> True leaves a file or folder out when a folder is expanded: FileZilla applies the
        # directory listing filters to folder transfers too.
        self.exclude = exclude or (lambda item: False)
        self.items: list[Item] = []
        self.lock = threading.RLock()
        self.ask_lock = threading.Lock()  # one question at a time, whatever the number of workers
        self.default_action = {"upload": None, "download": None}
        self.threads: list[threading.Thread] = []
        self.running = False
        self.cancelled: set[int] = set()

    # -------------------------------------------------------------------------- filling
    def add(self, items: list[Item]) -> None:
        with self.lock:
            self.items.extend(items)
        for it in items:
            self.on_change(it)

    def upload(self, local: str, remote_path: str) -> Item:
        st = os.stat(local)
        it = Item("upload", local, remote_path, 0 if os.path.isdir(local) else st.st_size, os.path.isdir(local),
                  st.st_mtime)
        self.add([it])
        return it

    def download(self, remote_path: str, local: str, entry: remote.Entry) -> Item:
        it = Item("download", local, remote_path, entry.size, entry.is_dir, entry.mtime)
        self.add([it])
        return it

    # -------------------------------------------------------------------------- running
    def start(self) -> None:
        """Process queue: workers start (more only if fewer are running than allowed)."""
        with self.lock:
            self.running = True
            self.threads = [t for t in self.threads if t.is_alive()]
            for _ in range(self.workers - len(self.threads)):
                t = threading.Thread(target=self._work, daemon=True)
                self.threads.append(t)
                t.start()

    def stop(self) -> None:
        """Stop processing: the transfers running now are cancelled and go back to the queue."""
        with self.lock:
            self.running = False
            for it in self.items:
                if it.status == "active":
                    self.cancelled.add(it.id)

    def wait(self, timeout: float = 60) -> bool:
        end = time.monotonic() + timeout
        for t in list(self.threads):
            t.join(max(0, end - time.monotonic()))
        return not any(t.is_alive() for t in self.threads)

    def cancel(self, ids) -> None:
        """Remove items from the queue; running ones are stopped."""
        ids = set(ids)
        with self.lock:
            for it in self.items:
                if it.id in ids and it.status == "active":
                    self.cancelled.add(it.id)
            self.items = [it for it in self.items if it.id not in ids or it.status == "active"]

    def retry_failed(self) -> None:
        with self.lock:
            for it in self.items:
                if it.status == "failed":
                    it.status, it.error, it.tries, it.transferred = "queued", "", 0, 0
                    self.on_change(it)

    def _next(self) -> Item | None:
        with self.lock:
            if not self.running:
                return None
            for it in self.items:
                if it.status == "queued":
                    it.status = "active"
                    it.started = time.monotonic()
                    return it
        return None

    def _work(self) -> None:
        sess = None
        try:
            while True:
                it = self._next()
                if it is None:
                    break
                self.on_change(it)
                while True:
                    try:
                        if sess is None or not sess.connected:
                            sess = self.connect()
                        self._one(sess, it)
                        break
                    except remote.HostKeyRejected as e:
                        self._fail(it, str(e))
                        break
                    except remote.RemoteError as e:
                        if it.id in self.cancelled:
                            self.cancelled.discard(it.id)
                            with self.lock:
                                it.status = "queued" if not self.running or it in self.items else "skipped"
                                it.transferred = 0
                            self.on_change(it)
                            break
                        lost = "Connection lost" in str(e) or "Could not connect" in str(e) or (
                            sess is not None and not sess.connected)
                        if lost and it.tries < RETRIES:
                            it.tries += 1
                            self.log("Status", f"Retrying {posixpath.basename(it.remote)} ({it.tries} of {RETRIES})")
                            if sess is not None:
                                sess.close()
                            sess = None
                            time.sleep(0.2 * it.tries)
                            continue
                        self._fail(it, str(e))
                        break
                    except OSError as e:
                        self._fail(it, e.strerror or str(e))
                        break
        finally:
            if sess is not None:
                sess.close()

    def _fail(self, it: Item, text: str) -> None:
        it.status, it.error = "failed", text
        self.log("Error", f"{os.path.basename(it.local) or it.remote}: {text}")
        self.on_change(it)

    def _done(self, it: Item, status: str = "done") -> None:
        it.status = status
        with self.lock:
            self.items = [x for x in self.items if x.id != it.id] + [it]  # finished ones go to the end
        self.on_change(it)

    # -------------------------------------------------------------------------- one item
    def _one(self, sess, it: Item) -> None:
        cancelled = (lambda: it.id in self.cancelled)
        if it.is_dir:
            self._expand(sess, it)
            return
        offset = 0
        if it.direction == "upload":
            target = self._remote_entry(sess, it.remote)
            if target is not None:
                action = self._decide(it, target.size, target.mtime)
                if isinstance(action, tuple):  # rename
                    it.remote = posixpath.join(posixpath.dirname(it.remote), action[1])
                    return self._one(sess, it)
                if action == "skip":
                    return self._done(it, "skipped")
                if action == "resume" and 0 < target.size < it.size:
                    offset = target.size
            it.transferred = offset

            def progress(n):
                it.transferred += n
                self.on_change(it)
            sess.upload(it.local, it.remote, offset, progress, cancelled)
        else:
            if os.path.exists(it.local):
                st = os.stat(it.local)
                action = self._decide(it, st.st_size, st.st_mtime)
                if isinstance(action, tuple):
                    it.local = os.path.join(os.path.dirname(it.local), action[1])
                    return self._one(sess, it)
                if action == "skip":
                    return self._done(it, "skipped")
                if action == "resume" and 0 < st.st_size < it.size:
                    offset = st.st_size
            os.makedirs(os.path.dirname(it.local) or ".", exist_ok=True)
            it.transferred = offset

            def progress(n):
                it.transferred += n
                self.on_change(it)
            sess.download(it.remote, it.local, offset, progress, cancelled)
        self._done(it)

    def _remote_entry(self, sess, path: str) -> remote.Entry | None:
        folder, name = posixpath.split(path)
        try:
            for e in sess.list(folder or "/"):
                if e.name == name:
                    return e
        except remote.RemoteError:
            return None
        return None

    def _decide(self, it: Item, target_size: int, target_mtime: float):
        """The file-exists question (or the answer given for all, per direction). Returns an action, or
        ("rename", new name)."""
        with self.ask_lock:
            action = self.default_action[it.direction]
            if action is None:
                if self.ask_exists is None:
                    return "overwrite"
                answer = self.ask_exists(Exists(it, it.size, it.mtime, target_size, target_mtime))
                if answer is None:
                    return "skip"
                action, extra = answer
                if action == "rename":
                    return ("rename", extra)
                if extra:  # "apply to all"
                    self.default_action[it.direction] = action
        newer = it.mtime > target_mtime + 1
        differs = it.size != target_size
        if action == "overwrite_newer":
            return "overwrite" if newer else "skip"
        if action == "overwrite_size":
            return "overwrite" if differs else "skip"
        if action == "overwrite_size_newer":
            return "overwrite" if differs or newer else "skip"
        if action == "resume" and not (0 < target_size < it.size):
            return "skip" if target_size >= it.size else "overwrite"
        return action

    def _expand(self, sess, it: Item) -> None:
        """A folder: make it on the other side and queue what's in it, right after it."""
        children: list[Item] = []
        if it.direction == "upload":
            try:
                sess.mkdir(it.remote)
            except remote.RemoteError:
                pass  # already there
            for name in sorted(os.listdir(it.local), key=str.lower):
                path = os.path.join(it.local, name)
                st = os.stat(path)
                d = os.path.isdir(path)
                children.append(Item("upload", path, posixpath.join(it.remote, name), 0 if d else st.st_size, d,
                                     st.st_mtime))
        else:
            os.makedirs(it.local, exist_ok=True)
            for e in sorted(sess.list(it.remote), key=lambda e: e.name.lower()):
                children.append(Item("download", os.path.join(it.local, e.name), posixpath.join(it.remote, e.name),
                                     e.size, e.is_dir, e.mtime))
        children = [c for c in children if not self.exclude(c)]
        with self.lock:
            i = next((k for k, x in enumerate(self.items) if x.id == it.id), len(self.items))
            self.items[i + 1:i + 1] = children
        for c in children:
            self.on_change(c)
        self._done(it)

    # -------------------------------------------------------------------------- what the window shows
    def snapshot(self) -> dict[str, list[Item]]:
        with self.lock:
            items = list(self.items)
        return {"queued": [i for i in items if i.status in ("queued", "active")],
                "failed": [i for i in items if i.status == "failed"],
                "done": [i for i in items if i.status in ("done", "skipped")]}

    def bytes_left(self) -> int:
        with self.lock:
            return sum(max(0, i.size - i.transferred) for i in self.items if i.status in ("queued", "active"))
