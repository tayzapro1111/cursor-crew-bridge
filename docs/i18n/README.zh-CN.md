# cursor-crew-bridge

Kiro Crew 桌面端不变。想走 Cursor 账单就用 `start-cursor-gateway`；想走官方 Kiro 就用 `start-kiro-default`。

[English](../../README.md) · [Русский](../../README.ru.md)

## 两条路

| 脚本 | 模型谁出 | 账单 |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | 官方 `kiro-cli` | Kiro 订阅 |

Autopilot 卡片是 Crew 的。Cursor 路径由本仓库补 plan/stage；Kiro 路径用官方 `prompt-orchestrator.md`。

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Windows 用 `setup.bat`。Linux 请设置 `KIROCREW_EXE`。安装说明：[docs/INSTALL.md](../INSTALL.md)。
