"""Pretend to be kiro-cli so Kiro Crew can spawn Cursor Agent over ACP."""

from __future__ import annotations

import json
import sys
from typing import Sequence

from cursor_crew_bridge.acp_bridge import run_acp
from cursor_crew_bridge.config import DEFAULT_AGENT_NAME, KIRO_VERSION_BANNER, catalog_models
from cursor_crew_bridge.cursor_cli import kiro_whoami_json, print_version


def _agent_name(args: Sequence[str]) -> str:
    if "--agent" in args:
        idx = args.index("--agent")
        if idx + 1 < len(args):
            return args[idx + 1]
    for item in args:
        if item.startswith("--agent="):
            return item.split("=", 1)[1]
    return DEFAULT_AGENT_NAME


def dispatch(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args == ["--version"] or args == ["-v"] or args == ["version"]:
        try:
            print_version()
        except FileNotFoundError:
            sys.stdout.write(KIRO_VERSION_BANNER + "\n")
            sys.stdout.flush()
        return 0

    if args and args[0] == "whoami":
        payload = kiro_whoami_json()
        if "--format" in args and "json" in args:
            sys.stdout.write(json.dumps(payload) + "\n")
        else:
            sys.stdout.write(payload.get("email", "cursor-local") + "\n")
        sys.stdout.flush()
        return 0

    if args[:2] == ["agent", "validate"] or (args and args[0] == "agent" and "validate" in args):
        return 0

    if args and args[0] == "chat":
        if "--list-models" in args:
            payload = {"models": catalog_models()}
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
            return 0
        sys.stdout.write("usage: bridged to Cursor (no Kiro credits)\n")
        sys.stdout.flush()
        return 0

    if args and args[0] == "acp":
        return run_acp(_agent_name(args))

    sys.stderr.write(
        "cursor-crew-bridge: expected --version, whoami, agent validate, or acp\n"
        f"got: {args!r}\n"
    )
    return 2


def main() -> None:
    raise SystemExit(dispatch())


if __name__ == "__main__":
    main()
