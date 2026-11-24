#!/usr/bin/env bash
# Easy launcher for the LibRead downloader (CLI) and its web GUI.
# Creates a virtual environment on first run and auto-installs requirements.
# Usage:
#   ./run.sh <series URL> [options]   # command-line downloader
#   ./run.sh gui [--port 8902]        # local web GUI (opens in browser)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# When launched by double-click there is no terminal window, so nothing is
# visible. Relaunch inside a terminal emulator so the app actually shows up.
if [ -z "${LIBREAD_INSIDE_TERM:-}" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && ! [ -t 1 ]; then
    export LIBREAD_INSIDE_TERM=1
    if command -v konsole >/dev/null 2>&1; then
        exec konsole --hold -e bash "$SCRIPT_DIR/run.sh" "$@"
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -hold -e bash "$SCRIPT_DIR/run.sh" "$@"
    fi
fi

PYTHON="${PYTHON:-python3}"
VENV_DIR="$SCRIPT_DIR/.venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found. Install Python 3.8+ first." >&2
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[setup] creating virtual environment in $VENV_DIR ..."
    if ! "$PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
        echo "[setup] python3-venv not available, falling back to system pip (--user)"
        if ! python3 -c "import requests, bs4" >/dev/null 2>&1; then
            python3 -m pip install --user -r requirements.txt
        fi
        exec python3 libread_dl.py "$@"
    fi
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! python -c "import requests, bs4" >/dev/null 2>&1; then
    echo "[setup] installing requirements ..."
    python -m pip install --upgrade pip >/dev/null
    python -m pip install -r requirements.txt
fi

# Double-clicking the app with no arguments opens the web GUI, which is the
# friendly entry point. Terminal users pass a series URL to use the CLI.
if [ "${1:-}" = "gui" ] || [ "$#" -eq 0 ]; then
    if [ "${1:-}" = "gui" ]; then
        shift
    fi
    exec python libread_gui.py "$@"
fi

exec python libread_dl.py "$@"
