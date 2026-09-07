# cursor-crew-bridge

Use o [Kiro Crew](https://github.com/kirodotdev/KiroCrew) com modelos do [Cursor Agent](https://cursor.com). Sem assinatura Kiro. A fatura vai para o Cursor.

É um *shim* **ACP**: o Crew acha que fala com `kiro-cli`; o backend é `cursor-agent acp`.

[English](../../README.md) · [Русский](../../README.ru.md)

## Instalação

**Windows:** instale o Kiro Crew → entre no Cursor → clone → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

No Linux defina `KIROCREW_EXE`. CLI do Cursor: `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` não imprime segredos. Cancel para o turno.
