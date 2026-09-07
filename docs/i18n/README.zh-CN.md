# cursor-crew-bridge

用 [Kiro Crew](https://github.com/kirodotdev/KiroCrew) 跑 [Cursor Agent](https://cursor.com) 模型。不需要 Kiro 订阅，账单走 Cursor。

这是 **ACP** 垫片：Crew 以为在跟 `kiro-cli` 说话，实际后端是 `cursor-agent acp`。

[English](../../README.md) · [Русский](../../README.ru.md)

## 安装

**Windows:** 安装 Kiro Crew → 登录 Cursor → 克隆仓库 → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

Linux 请设置 `KIROCREW_EXE`。Cursor CLI：`curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` 不会打印密钥。取消按钮会真正停止当前回合。
