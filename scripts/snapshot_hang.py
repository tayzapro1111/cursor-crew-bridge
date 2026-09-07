"""Snapshot hang evidence for Liquid Glass + Kiro Crew via Cursor Grok."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\Razrabotka\cursor-crew-bridge")
OUT = ROOT / ".bridge-logs" / "hang-2026-09-07"
CREW = Path.home() / ".kiro" / "crew"
TOKEN_RE = re.compile(r"(eyJ[A-Za-z0-9_-]{20,}|auth-token['\"]?\s*[:=]\s*['\"]?[^\s'\"]+)", re.I)

SESSIONS = {
    "liquid-glass": CREW / "sessions" / "dashboard_chat-4-1788794318.jsonl",
    "kiro-crew-grok": CREW / "sessions" / "dashboard_chat-6-1788812445.jsonl",
}


def redact(text: str) -> str:
    return TOKEN_RE.sub("<redacted>", text)


def copy_redacted(src: Path, dest: Path, max_bytes: int = 2_000_000) -> None:
    if not src.is_file():
        dest.write_text(f"missing: {src}\n", encoding="utf-8")
        return
    data = src.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    text = data.decode("utf-8", "replace")
    dest.write_text(redact(text), encoding="utf-8")


def parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_session(path: Path) -> dict:
    roles: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    events: list[dict] = []
    thinking = 0
    stops = 0
    injects = 0
    first_meta = {}
    last_user = None
    gaps: list[dict] = []
    pending_user: datetime | None = None

    if not path.is_file():
        return {"error": f"missing {path}"}

    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("_type") == "metadata":
                first_meta = {
                    "title": row.get("title"),
                    "model": row.get("model"),
                    "project": row.get("project"),
                    "created_at": row.get("created_at"),
                    "mode": row.get("mode"),
                }
                continue
            role = str(row.get("role") or "")
            roles[role] += 1
            ts = parse_ts(row.get("ts"))
            content = row.get("content")
            preview = ""
            kind = ""
            if isinstance(content, str):
                preview = content.replace("\n", " ")[:160]
                if content.startswith("{") and '"kind"' in content[:80]:
                    try:
                        payload = json.loads(content)
                        kind = str(payload.get("kind") or "")
                    except json.JSONDecodeError:
                        pass
                if role == "system" and "stop_event" in content:
                    stops += 1
                    kind = kind or "stop_event"
            if role == "inject":
                injects += 1
                kind = "inject"
            if role == "tool":
                kind = str((row.get("meta") or {}).get("kind") or "tool")
                kinds[kind] += 1
            lowered = preview.lower()
            if "thinking" in lowered or "thought" in lowered:
                thinking += 1
            if role == "user" and ts:
                pending_user = ts
                last_user = ts.isoformat()
            elif pending_user and ts and role in {"assistant", "tool", "inject", "system"}:
                delta = (ts - pending_user).total_seconds()
                if delta >= 5:
                    gaps.append(
                        {
                            "wait_s": round(delta, 1),
                            "from_user": pending_user.isoformat(),
                            "to": ts.isoformat(),
                            "to_role": role,
                            "preview": preview[:120],
                        }
                    )
                if role in {"assistant", "tool"}:
                    pending_user = None
            events.append(
                {
                    "n": line_no,
                    "ts": ts.isoformat() if ts else "",
                    "role": role,
                    "kind": kind,
                    "preview": preview[:140],
                }
            )

    big_gaps = sorted(gaps, key=lambda item: item["wait_s"], reverse=True)[:12]
    return {
        "file": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "meta": first_meta,
        "roles": dict(roles),
        "tool_kinds": dict(kinds),
        "thinking_mentions": thinking,
        "stop_events": stops,
        "injects": injects,
        "last_user_ts": last_user,
        "event_count": len(events),
        "last_events": events[-25:],
        "slowest_user_to_next": big_gaps,
        "open_user_wait": pending_user.isoformat() if pending_user else None,
    }


def parse_bridge(path: Path) -> dict:
    if not path.is_file():
        return {"error": f"missing {path}"}
    text = redact(path.read_text(encoding="utf-8", errors="replace"))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    interesting = [
        ln
        for ln in lines
        if any(
            key in ln
            for key in (
                "session/new",
                "split session",
                "StreamReader",
                "LimitOverrun",
                "spawn:",
                "local-ack",
                "auto-allow",
                "auto-reply",
                "window=",
                "mcp=",
                "ValueError",
                "skipped",
            )
        )
    ]
    mcp_starts: list[str] = []
    sid_ready: list[str] = []
    for ln in interesting:
        if "session/new cwd=" in ln:
            mcp_starts.append(ln)
        if "session/new sid=" in ln:
            sid_ready.append(ln)
    return {
        "path": str(path),
        "lines": len(lines),
        "interesting_tail": interesting[-80:],
        "session_new_cwd": mcp_starts[-20:],
        "session_new_sid": sid_ready[-20:],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    copies = {
        "bridge-project.log": ROOT / "bridge.log",
        "bridge-crew.log": CREW / "logs" / "cursor-crew-bridge.log",
        "gateway.log": CREW / "gateway.log",
        "open_slots.json": CREW / "open_slots.json",
        "session_map.json": CREW / "session_map.json",
        "model_windows.json": CREW / "model_windows.json",
    }
    for name, src in copies.items():
        copy_redacted(src, OUT / name, max_bytes=800_000)

    report: dict = {
        "captured_at": datetime.now().isoformat(),
        "sessions": {key: summarize_session(path) for key, path in SESSIONS.items()},
        "bridge": parse_bridge(ROOT / "bridge.log"),
        "bridge_crew": parse_bridge(CREW / "logs" / "cursor-crew-bridge.log"),
        "open_slots": json.loads((CREW / "open_slots.json").read_text(encoding="utf-8"))
        if (CREW / "open_slots.json").is_file()
        else {},
        "session_map_keys": list(json.loads((CREW / "session_map.json").read_text(encoding="utf-8")).keys())
        if (CREW / "session_map.json").is_file()
        else [],
    }
    (OUT / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # cursor agent logs: copy filenames + last 80 lines redacted
    scratch = CREW / "scratch"
    agent_notes = []
    if scratch.is_dir():
        logs = sorted(scratch.glob("**/cursor-agent-logs-admin/*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
        agent_dir = OUT / "cursor-agent-tails"
        agent_dir.mkdir(exist_ok=True)
        for log in logs:
            tail = "\n".join(redact(log.read_text(encoding="utf-8", errors="replace")).splitlines()[-60:])
            dest = agent_dir / f"{log.parent.parent.name}-{log.name}"
            dest.write_text(tail, encoding="utf-8")
            agent_notes.append({"file": str(log), "copied": dest.name, "bytes": log.stat().st_size})
    report["cursor_agent_logs"] = agent_notes
    (OUT / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(OUT))
    print("sessions", {k: v.get("meta", {}).get("title") for k, v in report["sessions"].items()})
    for key, data in report["sessions"].items():
        print(key, "roles", data.get("roles"), "stops", data.get("stop_events"), "injects", data.get("injects"))
        for gap in (data.get("slowest_user_to_next") or [])[:5]:
            print(" ", gap["wait_s"], "s", gap["to_role"], gap["preview"][:80])


if __name__ == "__main__":
    main()
