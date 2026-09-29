#!/usr/bin/env bash
# MedTracker one-step setup for macOS / Linux.
# Creates .venv in this folder, upgrades pip and installs all requirements.
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3.10 or newer was not found. Please install it first (see README.md)."
    exit 1
fi

$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
    echo "Python 3.10 or newer is required. You have: $($PY --version)"
    exit 1
}

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv ..."
    $PY -m venv .venv
fi

echo "Upgrading pip ..."
.venv/bin/python -m pip install --upgrade pip

echo "Installing requirements ..."
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt

echo
echo "Setup complete."
echo "  Start the app:      ./run.sh        (or ./run.sh --demo)"
echo "  Activate the venv:  source .venv/bin/activate"
