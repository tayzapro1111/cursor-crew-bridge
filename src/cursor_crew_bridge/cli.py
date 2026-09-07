"""Double-click entry: gateway (Cursor Grok) or default (official Kiro)."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cursor_crew_bridge.config import kirocrew_exe, official_kiro_cli, shim_kiro_cli
from cursor_crew_bridge.profiles import apply_default, apply_gateway, status_payload
from cursor_crew_bridge.reaper import reap_acp_leaks


DASHBOARD = "http://127.0.0.1:5476/"


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _running_image(image: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (result.stdout or "").lower()
    return image.lower() in text and "no tasks" not in text and "нет задач" not in text


def _stop_crew() -> None:
    if not _running_image("KiroCrew.exe"):
        return
    _print("Останавливаю KiroCrew, чтобы подхватить новый .env ...")
    subprocess.run(
        ["taskkill", "/IM", "KiroCrew.exe", "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    for _ in range(20):
        if not _running_image("KiroCrew.exe"):
            break
        time.sleep(0.25)


def _start_crew() -> Path | None:
    exe = kirocrew_exe()
    if not exe.is_file():
        if sys.platform == "win32":
            raise FileNotFoundError(f"KiroCrew.exe не найден: {exe}")
        _print(f"KiroCrew binary not found ({exe}). Set KIROCREW_EXE or start the app yourself.")
        return None
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return exe


def _wait_dashboard(seconds: float = 45) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(DASHBOARD, timeout=2) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    return False


def _preflight_gateway() -> None:
    if not shim_kiro_cli().is_file():
        raise FileNotFoundError(
            "Нет .venv\\Scripts\\kiro-cli.exe. Сначала запусти scripts\\install-into-crew.ps1"
        )
    from cursor_crew_bridge.cursor_auth import access_token
    from cursor_crew_bridge.cursor_cli import cursor_agent_argv

    if not access_token():
        raise RuntimeError(
            "Нет токена Cursor в IDE (state.vscdb). Один раз открой Cursor и залогинься — сам Cursor потом можно закрыть."
        )
    cursor_agent_argv()


def cmd_gateway() -> int:
    _print("=== Cursor Gateway для KiroCrew ===")
    _print("Cursor IDE запускать не нужно. Токен берётся из уже сохранённого логина.")
    _preflight_gateway()
    _stop_crew()
    leaks = reap_acp_leaks()
    if leaks:
        _print(f"Убрал зависшие Cursor ACP: {[item.pid for item in leaks]}")
    info = apply_gateway()
    _print(f"Модель: {info['model']}")
    _print(f"Окно контекста: {info.get('context_window_tokens') or 256000} токенов")
    _print(f"MCP серверов из kirocrew.json: {info['mcp_count']}")
    names = [str(name) for name in info.get("mcp_names") or [] if name]
    if names:
        _print("MCP: " + ", ".join(names))
    _print("KIROCREW_KIRO_BIN -> " + str(shim_kiro_cli()))
    started = _start_crew()
    if started is None:
        _print("Env written. Open Kiro Crew now — it will spawn this shim as kiro-cli.")
        return 0
    if _wait_dashboard():
        _print("Успешно. Открывай KiroCrew — Grok Extra High выбран, MCP подключены.")
        _print("Cursor отдельно запускать не надо.")
        return 0
    _print("KiroCrew запущен, дашборд ещё не ответил на http://127.0.0.1:5476/ — подожди пару секунд и открой приложение.")
    return 0


def cmd_default() -> int:
    _print("=== Обычный запуск KiroCrew (подписка Kiro) ===")
    official = official_kiro_cli()
    if not official.is_file():
        raise FileNotFoundError(f"Официальный kiro-cli не найден: {official}")
    _stop_crew()
    leaks = reap_acp_leaks()
    if leaks:
        _print(f"Убрал зависшие Cursor ACP: {[item.pid for item in leaks]}")
    apply_default()
    _print("KIROCREW_KIRO_BIN -> " + str(official))
    _print("Модель: auto (каталог Kiro)")
    _start_crew()
    if _wait_dashboard():
        _print("Успешно. KiroCrew на официальном kiro-cli. Кредиты Cursor сюда не идут.")
        return 0
    _print("KiroCrew запущен. Открой приложение.")
    return 0


def cmd_status() -> int:
    info = status_payload()
    _print(f"shim: {info['shim']}")
    _print(f"official: {info['official_kiro']}")
    _print(f"KiroCrew.exe: {info['kirocrew']}")
    _print(f"token_present: {info['token_present']}")
    _print(f"mcp_count: {info['mcp_count']}")
    _print("mcp: " + ", ".join(str(n) for n in info["mcp_names"] if n))
    _print(f"acp_leaks: {info['acp_leaks']}")
    _print(f"KiroCrew running: {_running_image('KiroCrew.exe')}")
    _print(f"Cursor.exe running: {_running_image('Cursor.exe')}")
    return 0


def cmd_doctor() -> int:
    from cursor_crew_bridge.doctor import format_report, required_failed, run_checks

    checks = run_checks()
    _print(format_report(checks))
    return 1 if required_failed(checks) else 0


def cmd_setup(args: list[str]) -> int:
    from cursor_crew_bridge.setup_cmd import cmd_setup as run_setup

    skip_install = "--no-install" in args
    return run_setup(install=not skip_install)


def cmd_help() -> int:
    _print(
        "\n".join(
            [
                "cursor-crew — Kiro Crew ↔ Cursor Agent bridge",
                "",
                "  setup      Create .venv, install the shim, write Crew .env",
                "  doctor     Check Python, Kiro Crew, Cursor login, Agent CLI",
                "  gateway    Point Crew at Cursor models and start the dashboard",
                "  default    Point Crew back at official kiro-cli (Kiro credits)",
                "  status     Short live status",
                "",
                "Windows first time:  setup.bat",
                "Windows every day:   start-cursor-gateway.bat",
                "macOS / Linux:       ./setup.sh && ./start-cursor-gateway.sh",
                "Back to official Kiro: start-kiro-default.bat  or  cursor-crew default",
            ]
        )
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = (args[0] if args else "help").strip().lower()
    try:
        if cmd in {"gateway", "cursor", "grok"}:
            code = cmd_gateway()
        elif cmd in {"default", "kiro", "official"}:
            code = cmd_default()
        elif cmd in {"status"}:
            code = cmd_status()
        elif cmd in {"doctor", "check"}:
            code = cmd_doctor()
        elif cmd in {"setup", "install"}:
            code = cmd_setup(args)
        elif cmd in {"help", "-h", "--help"}:
            code = cmd_help()
        else:
            _print("Unknown command. Try: cursor-crew help")
            code = 2
    except Exception as exc:
        _print("Ошибка: " + str(exc))
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
