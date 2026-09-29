#!/usr/bin/env bash
# From a Mac: build every version that can be built on this machine.
#
#   ./build-all.sh
#
#   macOS (this Mac's chip)  -> ./build.sh          (native)
#   Linux x86_64             -> ./build-linux.sh    (Docker)
#   Windows .exe and Intel Mac cannot be built on an Apple Silicon Mac:
#   push a version tag to GitHub and the workflow builds them (see README, step f).
set -e
cd "$(dirname "$0")"

./build.sh
if docker info >/dev/null 2>&1; then
    ./build-linux.sh amd64
else
    echo "Docker is not running - skipping the Linux build."
fi

echo
echo "Everything buildable on this Mac is in the dist folder:"
ls -1 dist | grep -E '\.(dmg|zip|exe)$' | sed 's/^/  dist\//'
echo
echo "For the Windows .exe (and Intel Mac): push a version tag to GitHub, e.g."
echo "  git tag v\$(.venv/bin/python -c 'import config; print(config.APP_VERSION)') && git push origin --tags"
