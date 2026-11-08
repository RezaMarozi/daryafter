#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"

VENV=".venv"
PYTHON="$VENV/bin/python"

if [[ ! -f "$VENV/.daryafter-ready" ]]; then
    echo "Setting up Daryafter for the first time..."

    if ! command -v python3 >/dev/null 2>&1; then
        echo "Python 3 was not found. Install Python 3.12 or newer."
        exit 1
    fi

    VERSION=$(python3 -c 'import sys; print(sys.version_info >= (3, 12))')
    if [[ "$VERSION" != "True" ]]; then
        echo "Daryafter requires Python 3.12 or newer."
        exit 1
    fi

    if [[ ! -x "$PYTHON" ]]; then
        python3 -m venv "$VENV"
    fi

    "$PYTHON" -m pip install -r requirements.txt
    touch "$VENV/.daryafter-ready"
fi

exec "$PYTHON" -m daryafter "$@"
