Cursor and official Kiro from one checkout.

## Launchers

- `start-cursor-gateway` — Cursor Agent (Grok Extra High), Autopilot plan/stage steers in this package
- `start-kiro-default` — official `kiro-cli`, native Kiro Autopilot

## Fixes in 0.4.0

- **Cancel** is a JSON-RPC notification. The session stays. «Отменить» no longer paints `[Stopped]` while the model keeps talking.
- Windows tool chips show `file.ts`, not `Edit ""`.
- Cursor todos land in the Crew sidebar.
- Token meter prefers Cursor `usage` when present; window is 256k.
- Install scripts for Windows, macOS, and Linux.

Wheels and sdists are attached to this release. Install: `pip install` the `.whl`, or clone and `setup.bat` / `./setup.sh`.

Details: [CHANGELOG.md](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/CHANGELOG.md) · [Autopilot](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/docs/AUTOPILOT.md)
