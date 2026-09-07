#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Run ./setup.sh first."
  exit 1
fi
exec .venv/bin/python -m cursor_crew_bridge.cli default
