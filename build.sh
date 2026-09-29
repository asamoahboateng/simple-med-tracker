#!/usr/bin/env bash
# Build MedTracker as a standalone app on macOS or Linux (one step).
#
#   ./build.sh
#
# macOS  -> dist/MedTracker.app, plus dist/MedTracker-<version>-macOS.dmg and .zip to share
# Linux  -> dist/MedTracker/ folder, plus dist/MedTracker-<version>-Linux.zip
#
# Uses only the project's .venv (run ./setup.sh first). Tests run before building.
set -e
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "The virtual environment is missing. Run ./setup.sh first."
    exit 1
fi
VERSION=$($PY -c "import config; print(config.APP_VERSION)")

echo "==> Running tests"
$PY -m pytest

echo "==> Building MedTracker $VERSION with PyInstaller"
$PY -m PyInstaller medtracker.spec --noconfirm --clean

if [ "$(uname)" = "Darwin" ]; then
    APP=dist/MedTracker.app
    ARCH=$(uname -m)
    echo "==> Creating ZIP"
    ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/MedTracker-$VERSION-macOS-$ARCH.zip"

    echo "==> Creating DMG (drag-to-Applications installer)"
    STAGE=$(mktemp -d)
    cp -R "$APP" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    rm -f "dist/MedTracker-$VERSION-macOS-$ARCH.dmg"
    hdiutil create -volname "MedTracker $VERSION" -srcfolder "$STAGE" -ov -format UDZO \
        "dist/MedTracker-$VERSION-macOS-$ARCH.dmg" >/dev/null
    rm -rf "$STAGE"

    echo
    echo "Done. Your files are in the dist folder:"
    echo "  dist/MedTracker.app                           (the app itself)"
    echo "  dist/MedTracker-$VERSION-macOS-$ARCH.dmg      (installer to share)"
    echo "  dist/MedTracker-$VERSION-macOS-$ARCH.zip      (zip to share)"
    echo "First launch on another Mac: try to open it, then System Settings -> Privacy & Security"
    echo "-> Open Anyway (or: xattr -dr com.apple.quarantine /Applications/MedTracker.app)."
else
    echo "==> Creating ZIP"
    (cd dist && rm -f "MedTracker-$VERSION-Linux.zip" && zip -qry "MedTracker-$VERSION-Linux.zip" MedTracker)
    echo
    echo "Done. Run dist/MedTracker/MedTracker, or share dist/MedTracker-$VERSION-Linux.zip"
fi
