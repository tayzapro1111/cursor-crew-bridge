#!/usr/bin/env bash
# First-time install for macOS and Linux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11+ is required. Install python3 and re-run ./setup.sh"
  exit 1
fi

PY=python3
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Need Python 3.11 or newer. Found: $("$PY" --version 2>&1)"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating .venv ..."
  "$PY" -m venv .venv
fi

echo "Installing cursor-crew-bridge ..."
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .

if ! command -v cursor-agent >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/cursor-agent" ]]; then
  echo "Cursor Agent CLI not on PATH. Installing from cursor.com ..."
  curl https://cursor.com/install -fsSL | bash || {
    echo "Install Cursor Agent CLI yourself: https://cursor.com/docs/cli/installation"
  }
fi

.venv/bin/python -m cursor_crew_bridge.cli setup --no-install
echo
echo "Next: ./start-cursor-gateway.sh"
echo "Or:   .venv/bin/cursor-crew gateway"
