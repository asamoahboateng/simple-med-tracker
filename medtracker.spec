# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build recipe for MedTracker.

Run from the project folder with the .venv active:
    pyinstaller medtracker.spec --noconfirm --clean

Output:
    Windows : dist/MedTracker/MedTracker.exe  (folder; installer/medtracker.iss packs it
                                               into MedTracker-Setup-<version>.exe)
    macOS   : dist/MedTracker.app          (application bundle)
    Linux   : dist/MedTracker/MedTracker   (folder with the program inside)

PyInstaller cannot cross-compile: build the Windows version on Windows, the
macOS version on a Mac, and the Linux version on Linux (or use GitHub Actions).
"""

import sys

sys.path.insert(0, SPECPATH)          # so we can read the version from config.py
from config import APP_NAME, APP_VERSION  # noqa: E402  (single source of truth)

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

if IS_WINDOWS:
    ICON = "resources/icon.ico"
elif IS_MAC:
    ICON = "resources/icon.icns"
else:
    ICON = "resources/icon.png"

# Heavy modules MedTracker never uses - excluding them keeps the build smaller.
# numpy and PIL are optional extras of openpyxl: it works without them. They are listed
# so an older .venv that still has them installed doesn't pull them into the build.
EXCLUDES = [
    "tkinter", "_tkinter", "IPython", "jupyter", "notebook", "ipykernel",
    "PyQt5", "PyQt6", "PySide2", "scipy", "pytest", "setuptools",
    "matplotlib", "pandas", "numpy", "PIL", "pytz", "dateutil",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtNetwork",
    # The sync server (server/) runs in Docker, never inside the app. Its packages are in
    # requirements-dev.txt, so keep them out even if something ever imports them by mistake.
    "sync_server", "fastapi", "starlette", "uvicorn", "psycopg", "psycopg_binary", "pydantic",
    "pydantic_core", "httpx2",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("resources", "resources")],   # icons, found at runtime via resource_path()
    # cloud_keys is imported by name (and only exists when built with keys); keyring finds
    # its password-store backends at runtime, so PyInstaller cannot see them.
    hiddenimports=["cloud_keys", "keyring.backends.Windows", "keyring.backends.macOS"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
# Qt's translations of its own dialogs (~7 MB) are never loaded: the app installs no
# QTranslator, so its dialogs are always in English.
a.datas = [d for d in a.datas if "Qt/translations" not in d[0].replace("\\", "/")]

pyz = PYZ(a.pure)

# All platforms: a folder build (starts faster, is required for a .app, and on Windows
# is what the Inno Setup installer packages so the app can update itself).
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="org.medtracker.app",
        version=APP_VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
