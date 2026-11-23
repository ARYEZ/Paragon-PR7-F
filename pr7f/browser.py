"""The browsing connection (the remote pane's), on its own thread so the window never waits for the network,
and the bridge that lets any thread ask the user something (host key, certificate, file exists).

Commands run one after another, as FileZilla's: each `run(fn, done, failed)` calls fn(session) on the thread and
hands the result to `done` (or the error to `failed`) on the GUI thread.
"""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, Signal

from . import remote, sites


class Asker(QObject):
    """ask(kind, payload) from any thread; the GUI thread answers through `handlers[kind](payload)`."""

    _asked = Signal(object)

    def __init__(self, handlers: dict):
        super().__init__()
        self.handlers = handlers
        self._asked.connect(self._answer)

    def _answer(self, box):
        kind, payload, holder, event = box
        try:
            holder.append(self.handlers[kind](payload))
        finally:
            event.set()

    def ask(self, kind: str, payload):
        if threading.current_thread() is threading.main_thread():
            return self.handlers[kind](payload)
        holder, event = [], threading.Event()
        self._asked.emit((kind, payload, holder, event))
        event.wait()
        return holder[0] if holder else None


class Browser(QObject):
    logged = Signal(str, str)
    _result = Signal(object)

    def __init__(self, asker: Asker):
        super().__init__()
        self.asker = asker
        self.site: remote.Site | None = None
        self.session = None
        self.jobs: queue.Queue = queue.Queue()
        self._result.connect(self._deliver)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.busy = 0

    # -------------------------------------------------------------------------- the thread
    def _loop(self):
        while True:
            job = self.jobs.get()
            if job is None:
                break
            fn, done, failed = job
            try:
                if self.session is None and fn is not _connect_marker:
                    raise remote.RemoteError("Not connected.")
                result = fn(self.session) if fn is not _connect_marker else self._connect()
                self._result.emit((done, result, None))
            except remote.RemoteError as e:
                if self.session is not None and not self.session.connected:
                    self.session = None
                self._result.emit((failed, None, str(e)))
            except Exception as e:  # noqa: BLE001 - shown, never lost in the thread
                self._result.emit((failed, None, f"{type(e).__name__}: {e}"))

    def _deliver(self, box):
        cb, result, error = box
        self.busy -= 1
        if error is not None:
            if cb:
                cb(error)
            else:
                self.logged.emit("Error", error)
        elif cb:
            cb(result)

    def run(self, fn, done=None, failed=None):
        self.busy += 1
        self.jobs.put((fn, done, failed))

    def wait_idle(self, timeout: float = 30) -> bool:
        """Tests: until every command so far has run and been delivered."""
        import time
        from PySide6.QtWidgets import QApplication
        end = time.monotonic() + timeout
        while self.busy and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.005)
        return not self.busy

    # -------------------------------------------------------------------------- connecting
    def log(self, kind, text):
        self.logged.emit(kind, text)

    def host_key_check(self, host, port, kind, fp, changed):
        return self.asker.ask("hostkey", {"host": host, "port": port, "kind": kind, "fingerprint": fp,
                                          "changed": changed})

    def cert_check(self, host, info):
        if sites.trusted_cert(host, info["sha256"]):
            return True
        answer = self.asker.ask("cert", {"host": host, **info})
        if answer == "always":
            sites.trust_cert(host, info["sha256"])
        return answer in ("once", "always")

    def open(self, site: remote.Site):
        """A new connection (in this thread's turn), for the browser or a queue worker."""
        return remote.open_session(site, self.log, self.host_key_check, sites.known_hosts_path(), self.cert_check)

    def _connect(self):
        if self.session is not None:
            self.session.close()
            self.session = None
        self.session = self.open(self.site)
        return self.session.cwd_path

    def connect(self, site: remote.Site, done=None, failed=None):
        self.site = site
        self.run(_connect_marker, done, failed)

    def disconnect(self):
        def close(sess):
            sess.close()
            self.session = None
        if self.session is not None:
            self.run(close)

    @property
    def connected(self) -> bool:
        return self.session is not None and self.session.connected

    def stop(self):
        self.jobs.put(None)


def _connect_marker(_):
    pass
