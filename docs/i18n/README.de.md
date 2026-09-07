# cursor-crew-bridge

[Kiro Crew](https://github.com/kirodotdev/KiroCrew) mit [Cursor Agent](https://cursor.com)-Modellen. Kein Kiro-Abo. Abrechnung über Cursor.

Das ist ein **ACP**-Shim: Crew spricht mit `kiro-cli`, hinten läuft `cursor-agent acp`.

[English](../../README.md) · [Русский](../../README.ru.md)

## Installation

**Windows:** Kiro Crew → in Cursor anmelden → klonen → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

Linux: `KIROCREW_EXE` setzen. Cursor CLI: `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` druckt keine Secrets. Cancel beendet den Turn.
