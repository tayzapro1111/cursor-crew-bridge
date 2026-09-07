# cursor-crew-bridge

**[Kiro Crew](https://github.com/kirodotdev/KiroCrew) на моделях [Cursor Agent](https://cursor.com). Без подписки Kiro. Без токенов Kiro. Тот же дашборд.**

`cursor-crew-bridge` — прослойка **ACP (Agent Client Protocol)**. Crew всегда говорит ACP с процессом `kiro-cli`. Этот репозиторий *и есть* тот процесс: дашборд тот же, счёт идёт в Cursor (по умолчанию Grok 4.6 Extra High).

[English](README.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [Español](docs/i18n/README.es.md) · [Deutsch](docs/i18n/README.de.md) · [Português](docs/i18n/README.pt-BR.md) · [Français](docs/i18n/README.fr.md) · [한국어](docs/i18n/README.ko.md)

[Как устроено](docs/HOW-IT-WORKS.md) · [Установка](docs/INSTALL.md) · [Конфиг](docs/CONFIGURATION.md) · [Поломки](docs/TROUBLESHOOTING.md)

Не связан с Kiro / AWS и Anysphere. Нужны приложение Kiro Crew и один логин в Cursor на этом ПК. Подписка Kiro CLI не нужна.

## За минуту

**Windows:** Kiro Crew → войти в Cursor → клонировать репо → `setup.bat` → `start-cursor-gateway.bat`.

```text
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
setup.bat
start-cursor-gateway.bat
```

**macOS / Linux:**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

На Linux задай `KIROCREW_EXE` на бинарник Kiro Crew.

## Что чинит мост

- Пилюли `Editing file.ts`, а не `Edit ""`
- Кнопка **Отменить** останавливает ход Cursor (`session/cancel` — notification, сессия живая)
- Autopilot текстом, как у нативного Fable
- Метр контекста 256k
- Список задач Cursor в сайдбаре Crew

Вернуться на официальный Kiro: `start-kiro-default.bat` или `./start-kiro-default.sh`.
