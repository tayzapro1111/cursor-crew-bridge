"""Create the venv launcher and write Crew .env. Does not start KiroCrew."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cursor_crew_bridge.config import discover_project_dir, shim_kiro_cli
from cursor_crew_bridge.doctor import format_report, required_failed, run_checks
from cursor_crew_bridge.install_env import upsert_env_file


def _venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def ensure_venv(root: Path) -> Path:
    py = _venv_python(root)
    if py.is_file():
        return py
    subprocess.run(
        [sys.executable, "-m", "venv", str(root / ".venv")],
        check=True,
    )
    if not py.is_file():
        raise FileNotFoundError(f"venv python missing after create: {py}")
    return py


def install_editable(root: Path, py: Path) -> None:
    subprocess.run([str(py), "-m", "pip", "install", "-U", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-e", str(root)], check=True)


def cmd_setup(*, install: bool = True) -> int:
    root = discover_project_dir()
    print(f"Project: {root}")
    if install:
        py = ensure_venv(root)
        print(f"venv: {py}")
        install_editable(root, py)
    launcher = shim_kiro_cli()
    if not launcher.is_file():
        print(f"Error: shim not created: {launcher}")
        return 1
    env_path = upsert_env_file(launcher)
    print(f"Wrote {env_path}")
    print(f"KIROCREW_KIRO_BIN={launcher}")
    checks = run_checks()
    print("")
    print(format_report(checks))
    if required_failed(checks):
        return 1
    print("")
    if sys.platform == "win32":
        print("Next: double-click start-cursor-gateway.bat  (or:  cursor-crew gateway)")
    else:
        print("Next: ./start-cursor-gateway.sh  (or:  .venv/bin/cursor-crew gateway)")
    return 0
