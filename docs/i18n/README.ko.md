# cursor-crew-bridge

Kiro Crew 화면은 그대로입니다. Cursor로 결제하려면 `start-cursor-gateway`, 공식 Kiro로 돌아가려면 `start-kiro-default`.

[English](../../README.md) · [Русский](../../README.ru.md)

| 실행 | 엔진 | 결제 |
|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor |
| `start-kiro-default` | 공식 `kiro-cli` | Kiro 구독 |

Autopilot 카드는 Crew 것입니다. Cursor 경로는 이 저장소가 plan/stage를 보강하고, Kiro 경로는 `prompt-orchestrator.md`를 씁니다.

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Windows는 `setup.bat`. [설치](../INSTALL.md)
