"""Start PR7-F.

    PR7-F.exe [ftp://user@host:port | sftp://... | folder]   FileZilla's command line: connect at once, or open a folder
    PR7-F.exe --check URL OUT.json                           connect, list /, write what was found (CI checks the
                                                             built program with it)
"""

from __future__ import annotations

import os
import sys


def check(url: str, out: str) -> int:
    import json
    from . import remote
    result = {}
    try:
        site = remote.parse_quick(url)
        sess = remote.open_session(site, host_key_check=lambda *a: "once")
        result = {"encrypted": sess.encrypted, "names": sorted(e.name for e in sess.list("/"))}
        sess.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if "names" in result else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--check"] and len(argv) == 3:
        return check(argv[1], argv[2])
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-F")
    theme.set_finish(settings.get("finish", "obsidian"))
    theme.load_fonts()
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    folder = next((a for a in argv if os.path.isdir(a)), None)
    w = MainWindow(folder)
    w.show()
    from . import update_ui
    update_ui.start(w)  # a check for updates, once a day
    url = next((a for a in argv if "://" in a), None)
    if url:
        from . import remote
        try:
            w.connect_to(remote.parse_quick(url))
        except remote.RemoteError as e:
            w.log("Error", str(e))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
