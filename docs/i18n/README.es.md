# cursor-crew-bridge

La app de Kiro Crew no cambia. `start-cursor-gateway` cobra en Cursor. `start-kiro-default` vuelve al `kiro-cli` oficial.

[English](../../README.md) · [Русский](../../README.ru.md)

| Arranque | Motor | Factura |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | `kiro-cli` oficial | suscripción Kiro |

Las tarjetas de Autopilot son de Crew. En Cursor este repo añade el contrato de plan/etapa. En Kiro manda `prompt-orchestrator.md`.

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

En Windows: `setup.bat`. [Instalación](../INSTALL.md)
