Kiro Crew on the left. Cursor Agent (Grok Extra High) or official `kiro-cli` on the right.

## Launchers

- `start-cursor-gateway` — Cursor Agent, Autopilot plan/stage steers in this package
- `start-kiro-default` — official `kiro-cli`, native Kiro Autopilot

## 0.8.0

First GitHub tag after `v0.4.0`. The Crew-facing child now answers as `kiro-cli` 2.15.0: `agentInfo`, slash-command roster, MCP `server_initialized` banners, tool `_meta.kiro.toolName`, local `/help` `/usage` `/tools` `/context` `/clear`, and `/compact` that rotates the Cursor session without wiping Crew JSONL.

`/compact` no longer photofinishes on a blocked Cursor stdout pump. Compaction status is emitted while the prompt is still open, then a real assistant line, then `end_turn` — otherwise Crew purges the stream and leaves Resume.

Wheels and sdists are attached. Install: `pip install` the `.whl`, or clone and `setup.bat` / `./setup.sh`.

Details: [CHANGELOG.md](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/CHANGELOG.md) · [Autopilot](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/docs/AUTOPILOT.md)
