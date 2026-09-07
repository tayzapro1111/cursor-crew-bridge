# cursor-crew-bridge

Дашборд Kiro Crew. Счёт — в Cursor, если запустил `start-cursor-gateway`. Официальный Kiro — одной командой рядом.

[English](README.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [Español](docs/i18n/README.es.md) · [Deutsch](docs/i18n/README.de.md) · [Português](docs/i18n/README.pt-BR.md) · [Français](docs/i18n/README.fr.md) · [한국어](docs/i18n/README.ko.md)

[Установка](docs/INSTALL.md) · [Autopilot](docs/AUTOPILOT.md) · [Как устроено](docs/HOW-IT-WORKS.md) · [Переменные](docs/CONFIGURATION.md) · [Поломки](docs/TROUBLESHOOTING.md) · [Релизы](https://github.com/Chumbayoumba/cursor-crew-bridge/releases)

## Два пути

| Команда | Модель | Оплата | Autopilot |
|---|---|---|---|
| `start-cursor-gateway` | Cursor Grok Extra High | Cursor | Карточки Crew + руль плана/стейджа из этого пакета |
| `start-kiro-default` | Официальный `kiro-cli` | подписка Kiro | Нативный Kiro, файл `prompt-orchestrator.md` |

История чата лежит у Crew. Менять бэкенд можно каждый день.

## Установка

Windows: поставь Kiro Crew, один раз войди в Cursor, дальше:

```bat
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
setup.bat
start-cursor-gateway.bat
```

Нет `cursor-agent` — запусти `setup.ps1`.

macOS / Linux:

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

На Linux укажи `KIROCREW_EXE`. Вернуться на Kiro: `start-kiro-default.bat` / `./start-kiro-default.sh`.

К проекту не относятся AWS и Anysphere. Нужно приложение Crew. Подписка Kiro нужна только второму пути.

## Пакет

Колесо на [Releases](https://github.com/Chumbayoumba/cursor-crew-bridge/releases). Из клона: `pip install -e ".[dev]"`.
