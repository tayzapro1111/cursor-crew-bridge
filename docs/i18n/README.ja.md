# cursor-crew-bridge

[Kiro Crew](https://github.com/kirodotdev/KiroCrew) から [Cursor Agent](https://cursor.com) のモデルを使います。Kiro のサブスクは不要です。請求は Cursor 側です。

これは **ACP** シムです。Crew は `kiro-cli` だと思い、実体は `cursor-agent acp` です。

[English](../../README.md) · [Русский](../../README.ru.md)

## インストール

**Windows:** Kiro Crew を入れる → Cursor にログイン → クローン → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

Linux では `KIROCREW_EXE` を設定。Cursor CLI: `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` は秘密を出しません。Cancel はターンを止めます。
