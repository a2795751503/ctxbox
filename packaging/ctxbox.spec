# PyInstaller spec for ctxbox (Windows / macOS / Linux)
# Build: pyinstaller packaging/ctxbox.spec --noconfirm
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = collect_submodules("ctxbox.core.adapters")

a = Analysis(
    ["../src/ctxbox/gui/app.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden + ["pydantic", "platformdirs", "charset_normalizer"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PyQt5", "PyQt6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ctxbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # GUI app
    icon="../packaging/icons/ctxbox.ico" if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ctxbox",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ctxbox.app",
        bundle_identifier="dev.ctxbox.app",
        info_plist={"NSHighResolutionCapable": "True"},
    )
