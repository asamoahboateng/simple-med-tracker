#!/usr/bin/env bash
# Start MedTracker using the project's virtual environment (no activation needed).
# Pass --demo to use the separate demo database:  ./run.sh --demo
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "The virtual environment is missing. Run ./setup.sh first."
    exit 1
fi
exec .venv/bin/python main.py "$@"
