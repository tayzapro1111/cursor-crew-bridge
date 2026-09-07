# cursor-crew-bridge

Utilisez [Kiro Crew](https://github.com/kirodotdev/KiroCrew) avec les modèles [Cursor Agent](https://cursor.com). Pas d’abonnement Kiro. La facture va chez Cursor.

C’est un *shim* **ACP** : Crew croit parler à `kiro-cli` ; le backend est `cursor-agent acp`.

[English](../../README.md) · [Русский](../../README.ru.md)

## Installation

**Windows :** installer Kiro Crew → se connecter à Cursor → cloner → `setup.bat` → `start-cursor-gateway.bat`

**macOS / Linux :**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh
./setup.sh
./start-cursor-gateway.sh
```

Sous Linux, définissez `KIROCREW_EXE`. CLI Cursor : `curl https://cursor.com/install -fsSL | bash`

`cursor-crew doctor` n’affiche aucun secret. Cancel arrête le tour.
