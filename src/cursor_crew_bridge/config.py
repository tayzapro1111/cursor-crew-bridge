"""Paths, model pin, and log file for the Crew ↔ Cursor ACP bridge."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

BRIDGE_VERSION = "0.8.2"
KIRO_AGENT_NAME = "kiro-cli"
KIRO_AGENT_VERSION = "2.15.0"
KIRO_VERSION_BANNER = f"{KIRO_AGENT_NAME} {KIRO_AGENT_VERSION}-cursor-crew-bridge"

# Cursor CLI accepts effort as a model suffix. Extra high is what this host
# asked for; Fast is left off so billing stays on the standard Grok 4.6 pool.
KNOWN_GROK_MODELS = frozenset(
    {
        "cursor-grok-4.6-low",
        "cursor-grok-4.6-low-fast",
        "cursor-grok-4.6-medium",
        "cursor-grok-4.6-medium-fast",
        "cursor-grok-4.6-high",
        "cursor-grok-4.6-high-fast",
        "cursor-grok-4.6-xhigh",
        "cursor-grok-4.6-xhigh-fast",
    }
)
BARE_GROK_ALIASES = frozenset({"cursor-grok-4.6", "grok-4.6", "grok", "grok-4.6-fast"})


def _normalize_full_model(value: str) -> str:
    raw = (value or "").strip()
    if raw.lower() in KNOWN_GROK_MODELS:
        return raw
    return "cursor-grok-4.6-xhigh"


def _normalize_lite_model(value: str) -> str:
    raw = (value or "").strip()
    lowered = raw.lower()
    if lowered in KNOWN_GROK_MODELS:
        return raw
    return "cursor-grok-4.6-high-fast"


def resolve_cursor_model(model_id: str, *, lite: bool = False) -> str:
    """Never return a Cursor model id that the CLI will reject."""

    raw = (model_id or "").strip()
    if lite:
        return _normalize_lite_model(raw)
    if raw.lower() in KNOWN_GROK_MODELS:
        return raw
    if "xhigh" in raw.lower():
        return "cursor-grok-4.6-xhigh"
    return _normalize_full_model(raw)


DEFAULT_MODEL = _normalize_full_model(os.environ.get("CURSOR_CREW_MODEL", "cursor-grok-4.6-xhigh"))
# Bare `cursor-grok-4.6` is NOT in Cursor's catalog. Optimizer / kirocrew-lite
# must use a suffixed id. high-fast: no Extra High thinking, first token sooner.
# (v0.2.3 used the bare id → Cursor died in ~3s, Optimize Prompt looked dead.)
LITE_MODEL = _normalize_lite_model(os.environ.get("CURSOR_CREW_LITE_MODEL", "cursor-grok-4.6-high-fast"))
LITE_AGENTS = frozenset({"kirocrew-lite"})
TRACE_DEFAULT = os.environ.get("CURSOR_CREW_TRACE", "1").strip().lower() not in {"0", "false", "no", "off"}
_DUMP_OFF = {"", "0", "false", "no", "off"}
_DUMP_ON = {"1", "true", "yes", "on"}
DEFAULT_AGENT_NAME = "kirocrew"
# Cursor Grok 4.6 Extra High window. Advertising 1M made Crew autocompact and
# the meter run at the wrong scale, so the model hit 256k while the UI still
# showed "plenty of room".
CONTEXT_WINDOW_TOKENS = int(os.environ.get("CURSOR_CREW_CONTEXT_WINDOW", "256000"))

GROK_BIN_MARKER = os.path.normcase(str(Path.home() / ".grok" / "bin" / "agent.exe"))
_LEGACY_PROJECT_DIR = Path(r"D:\Razrabotka\cursor-crew-bridge")


def _looks_like_project_root(path: Path) -> bool:
    marker = path / "pyproject.toml"
    if not marker.is_file():
        return False
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return False
    return "cursor-crew-bridge" in text


def discover_project_dir(*, start: Path | None = None) -> Path:
    """Repo root for this checkout. Never require a hardcoded D:\\ path."""

    override = os.environ.get("CURSOR_CREW_HOME", "").strip()
    if override:
        return Path(override)
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if _looks_like_project_root(candidate):
            return candidate
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = Path(".")
    for candidate in (cwd, *cwd.parents):
        if _looks_like_project_root(candidate):
            return candidate
    if _looks_like_project_root(_LEGACY_PROJECT_DIR):
        return _LEGACY_PROJECT_DIR
    if here.name == "config.py" and len(here.parents) >= 2:
        return here.parents[2]
    return cwd


PROJECT_DIR = discover_project_dir()


def data_home() -> Path:
    return Path.home() / ".kiro" / "crew"


def agents_dir() -> Path:
    return Path.home() / ".kiro" / "agents"


def _try_prepare(path: Path) -> Path | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
        return path
    except OSError:
        return None


def log_paths() -> list[Path]:
    """Every writable log target. Crew sandbox can block ~/.kiro/crew/logs."""

    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        key = os.path.normcase(str(path))
        if key in seen:
            return
        prepared = _try_prepare(path)
        if prepared is None:
            return
        seen.add(key)
        found.append(prepared)

    override = os.environ.get("CURSOR_CREW_BRIDGE_LOG", "").strip()
    if override:
        add(Path(override))
    add(data_home() / "logs" / "cursor-crew-bridge.log")
    add(PROJECT_DIR / "bridge.log")
    scratch = os.environ.get("KIROCREW_SCRATCH", "").strip()
    if scratch:
        add(Path(scratch) / "cursor-crew-bridge.log")
    try:
        add(Path.cwd() / "cursor-crew-bridge.log")
    except OSError:
        pass
    add(Path(tempfile.gettempdir()) / "cursor-crew-bridge.log")
    return found


def dump_acp_path() -> Path | None:
    """Optional redacted JSONL of Crew↔shim↔Cursor ACP. Off unless CURSOR_CREW_DUMP is set."""

    raw = os.environ.get("CURSOR_CREW_DUMP", "").strip()
    key = raw.lower()
    if key in _DUMP_OFF:
        return None
    if key in _DUMP_ON:
        return _try_prepare(data_home() / "logs" / "acp-dump.jsonl")
    return Path(raw)


def log_path() -> Path:
    paths = log_paths()
    if paths:
        return paths[0]
    return Path(tempfile.gettempdir()) / "cursor-crew-bridge.log"


def crew_env_path() -> Path:
    return data_home() / ".env"


def skip_mcp() -> bool:
    # Gateway wants the agent MCP roster. Opt out with CURSOR_CREW_SKIP_MCP=1.
    raw = os.environ.get("CURSOR_CREW_SKIP_MCP", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_lite_agent(agent: str | None) -> bool:
    return (agent or "").strip().lower() in LITE_AGENTS


def catalog_models() -> list[dict[str, object]]:
    """Rows for `kiro-cli chat --list-models`.

    Crew's picker entitlement compares catalog ``model_name`` to the
    ``modelId`` values from ACP ``session/new``. If those strings differ, the
    row shows a lock and cannot be selected.
    """

    rows = [
        {
            "model_id": DEFAULT_MODEL,
            "model_name": DEFAULT_MODEL,
            "context_window_tokens": CONTEXT_WINDOW_TOKENS,
        }
    ]
    if LITE_MODEL and LITE_MODEL != DEFAULT_MODEL:
        rows.append(
            {
                "model_id": LITE_MODEL,
                "model_name": LITE_MODEL,
                "context_window_tokens": CONTEXT_WINDOW_TOKENS,
            }
        )
    return rows


def advertised_model_aliases() -> list[tuple[str, str]]:
    """(modelId, display name) injected into session/new availableModels."""

    label = "Grok 4.6 Extra High"
    aliases = [
        (DEFAULT_MODEL, label),
        ("auto", label),
        ("claude-opus-5", label),
    ]
    if LITE_MODEL and LITE_MODEL != DEFAULT_MODEL:
        aliases.append((LITE_MODEL, "Grok 4.6 High Fast"))
    seen = {item[0] for item in aliases}
    extra = []
    for row in catalog_models():
        mid = str(row.get("model_id") or "")
        name = str(row.get("model_name") or mid)
        if mid and mid not in seen:
            extra.append((mid, name))
            seen.add(mid)
        if name and name not in seen:
            extra.append((name, name))
            seen.add(name)
    return aliases + extra


def gateway_window_keys() -> list[str]:
    """Crew ``model_windows.json`` keys that must match Extra High's 256k."""

    keys = [
        DEFAULT_MODEL,
        "auto",
        "Auto",
        "claude-opus-5",
        "Grok 4.6 Extra High",
        "Grok 4.6",
        "cursor-grok-4.6-high",
        "cursor-grok-4.6-high-fast",
        "cursor-grok-4.6",
    ]
    seen = {item.lower() for item in keys}
    extra: list[str] = []
    for model_id, name in advertised_model_aliases():
        for item in (model_id, name):
            if item and item.lower() not in seen:
                extra.append(item)
                seen.add(item.lower())
    return keys + extra


def official_kiro_cli() -> Path:
    override = os.environ.get("KIRO_OFFICIAL_BIN", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Kiro-Cli" / "kiro-cli.exe"
    for candidate in (
        Path.home() / ".local" / "bin" / "kiro-cli",
        Path("/usr/local/bin/kiro-cli"),
        Path("/opt/homebrew/bin/kiro-cli"),
    ):
        if candidate.is_file():
            return candidate
    return Path.home() / ".local" / "bin" / "kiro-cli"


def kirocrew_exe() -> Path:
    override = os.environ.get("KIROCREW_EXE", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Programs" / "KiroCrew" / "KiroCrew.exe"
    mac = Path("/Applications/KiroCrew.app/Contents/MacOS/KiroCrew")
    if mac.is_file():
        return mac
    for candidate in (
        Path.home() / ".local" / "bin" / "KiroCrew",
        Path("/usr/local/bin/KiroCrew"),
        Path("/opt/KiroCrew/KiroCrew"),
    ):
        if candidate.is_file():
            return candidate
    return Path.home() / ".local" / "bin" / "KiroCrew"


def shim_kiro_cli() -> Path:
    root = discover_project_dir()
    win = root / ".venv" / "Scripts" / "kiro-cli.exe"
    unix = root / ".venv" / "bin" / "kiro-cli"
    if win.is_file():
        return win
    if unix.is_file():
        return unix
    return win if os.name == "nt" else unix
