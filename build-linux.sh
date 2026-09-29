#!/usr/bin/env bash
# Build the LINUX version of MedTracker from a Mac (or any machine) using Docker.
#
#   ./build-linux.sh            # x86_64 / amd64 build (most Linux PCs)
#   ./build-linux.sh arm64      # ARM build (e.g. Raspberry Pi 4/5 64-bit)
#
# Needs Docker Desktop running. The build happens inside an Ubuntu 22.04 container
# (older glibc = runs on more Linux versions: Ubuntu 22.04+, Debian 12+, Mint 21+ ...).
# The container has its own virtual environment, so your Mac's .venv is not touched.
#
# Output: dist/linux-<arch>/MedTracker/  and  dist/MedTracker-<version>-Linux-<arch>.zip
set -e
cd "$(dirname "$0")"

ARCH="${1:-amd64}"
case "$ARCH" in
    amd64|x86_64) ARCH=amd64 ;;
    arm64|aarch64) ARCH=arm64 ;;
    *) echo "Unknown architecture '$ARCH' (use amd64 or arm64)"; exit 1 ;;
esac

if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Start Docker Desktop and try again."
    exit 1
fi

echo "==> Building MedTracker for Linux ($ARCH) inside Docker - the first run takes a while"
docker run --rm --platform "linux/$ARCH" \
    -v "$PWD":/src -w /src \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 -e DEBIAN_FRONTEND=noninteractive \
    ubuntu:22.04 bash -euo pipefail -c '
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends python3 python3-venv python3-dev \
            binutils zip libglib2.0-0 \
            libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 \
            libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 \
            libxcb-randr0 libxcb-render-util0 libxcb-image0 >/dev/null
        python3 -m venv /opt/venv                        # the container-only .venv
        /opt/venv/bin/python -m pip install -q --upgrade pip
        /opt/venv/bin/python -m pip install -q -r requirements.txt -r requirements-dev.txt
        echo "==> Running tests"
        /opt/venv/bin/python -m pytest -p no:cacheprovider
        echo "==> Running PyInstaller"
        /opt/venv/bin/python -m PyInstaller medtracker.spec --noconfirm --clean \
            --distpath "dist/linux-'"$ARCH"'" --workpath "build/linux-'"$ARCH"'"
        VERSION=$(/opt/venv/bin/python -c "import config; print(config.APP_VERSION)")
        cd "dist/linux-'"$ARCH"'"
        rm -f "../MedTracker-$VERSION-Linux-'"$ARCH"'.zip"
        zip -qry "../MedTracker-$VERSION-Linux-'"$ARCH"'.zip" MedTracker
        chown -R '"$(id -u):$(id -g)"' /src/dist /src/build
    '

VERSION=$(.venv/bin/python -c "import config; print(config.APP_VERSION)" 2>/dev/null || echo "?")
echo
echo "Done. Linux build:"
echo "  dist/linux-$ARCH/MedTracker/MedTracker          (the program)"
echo "  dist/MedTracker-$VERSION-Linux-$ARCH.zip        (zip to share)"
