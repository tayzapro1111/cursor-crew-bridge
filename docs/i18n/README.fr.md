# cursor-crew-bridge

L’app Kiro Crew ne bouge pas. `start-cursor-gateway` facture chez Cursor. `start-kiro-default` remet le `kiro-cli` officiel.

[English](../../README.md) · [Русский](../../README.ru.md)

| Lanceur | Moteur | Facture |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | `kiro-cli` officiel | abonnement Kiro |

Les cartes Autopilot viennent de Crew. Côté Cursor, ce dépôt injecte le contrat plan/étape. Côté Kiro, c’est `prompt-orchestrator.md`.

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Windows : `setup.bat`. [Installation](../INSTALL.md)
