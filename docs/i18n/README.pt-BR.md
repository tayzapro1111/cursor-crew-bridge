# cursor-crew-bridge

O app Kiro Crew continua o mesmo. `start-cursor-gateway` manda a fatura para o Cursor. `start-kiro-default` devolve o `kiro-cli` oficial.

[English](../../README.md) · [Русский](../../README.ru.md)

| Atalho | Motor | Conta |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | `kiro-cli` oficial | assinatura Kiro |

Os cards do Autopilot são do Crew. No caminho Cursor este pacote manda o contrato de plano/etapa. No Kiro vale `prompt-orchestrator.md`.

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Windows: `setup.bat`. [Instalação](../INSTALL.md)
