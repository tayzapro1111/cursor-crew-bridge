# cursor-crew-bridge

[Kiro Crew](https://github.com/kirodotdev/KiroCrew)에서 [Cursor Agent](https://cursor.com) 모델을 씁니다. Kiro 구독 없이 Cursor 요금만 나갑니다.

**ACP** 심입니다. Crew는 `kiro-cli`와 대화한다고 생각하고, 실제 백엔드는 `cursor-agent acp`입니다.

[English](../../README.md) · [Русский](../../README.ru.md)

## 설치

**Windows:** Kiro Crew 설치 → Cursor 로그인 → 클론 → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

Linux에서는 `KIROCREW_EXE`를 지정하세요. Cursor CLI: `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor`는 비밀을 출력하지 않습니다. Cancel은 턴을 멈춥니다.
