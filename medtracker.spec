# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build recipe for MedTracker.

Run from the project folder with the .venv active:
    pyinstaller medtracker.spec --noconfirm --clean

Output:
    Windows : dist/MedTracker.exe          (one single file)
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
EXCLUDES = [
    "tkinter", "_tkinter", "IPython", "jupyter", "notebook", "ipykernel",
    "PyQt5", "PyQt6", "PySide2", "scipy", "pytest", "setuptools",
    "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_webagg",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("resources", "resources")],   # icons, found at runtime via resource_path()
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WINDOWS:
    # Windows: one single .exe file, no console window.
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=APP_NAME,
        icon=ICON,
        console=False,
        upx=False,
        runtime_tmpdir=None,
    )
else:
    # macOS / Linux: a folder build (starts faster, and is required for a .app).
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
