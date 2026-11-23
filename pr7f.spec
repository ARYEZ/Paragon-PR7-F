# PyInstaller build of PR7-F: pyinstaller pr7f.spec  ->  dist/PR7-F/PR7-F.exe  (folder build: starts fast)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
a = Analysis(
    [str(root / "tools" / "launcher.py")],
    pathex=[str(root)],
    datas=[(str(root / "pr7f" / "fonts"), "pr7f/fonts"), (str(root / "pr7f" / "icons"), "pr7f/icons")],
    hiddenimports=collect_submodules("keyring.backends") + ["paramiko", "cryptography"],  # keyring finds its backends at run time
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PR7-F", console=False,
          icon=str(root / "pr7f" / "icons" / "app.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="PR7-F")
