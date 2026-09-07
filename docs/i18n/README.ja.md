# cursor-crew-bridge

Kiro Crew の画面はそのまま。Cursor の請求にしたいときは `start-cursor-gateway`。公式 Kiro に戻すときは `start-kiro-default`。

[English](../../README.md) · [Русский](../../README.ru.md)

| 起動 | 中身 | 支払い |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | 公式 `kiro-cli` | Kiro |

Autopilot のカードは Crew 側です。Cursor 経路ではこのリポジトリが plan/stage を補い、Kiro 経路では `prompt-orchestrator.md` が動きます。

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Windows は `setup.bat`。[インストール](../INSTALL.md)
