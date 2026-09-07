# cursor-crew-bridge

Usa [Kiro Crew](https://github.com/kirodotdev/KiroCrew) con modelos de [Cursor Agent](https://cursor.com). Sin suscripción Kiro. La factura va a Cursor.

Es un *shim* **ACP**: Crew cree hablar con `kiro-cli`; el backend es `cursor-agent acp`.

[English](../../README.md) · [Русский](../../README.ru.md)

## Instalación

**Windows:** instala Kiro Crew → inicia sesión en Cursor → clona → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

En Linux define `KIROCREW_EXE`. CLI de Cursor: `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` no imprime secretos. Cancel detiene el turno.
