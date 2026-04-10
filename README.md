# LAS — Lotto Analyzer System (GTK4 Desktop Client)

GTK4/Adwaita Desktop-App fuer **Lotto 6aus49** und **EuroJackpot**. Verbindet sich via REST-API mit dem LASS-Server.

## Features

- **15 Seiten** — Dashboard, Generator, Statistik, Backtest, AI-Chat, Berichte, Telegram, ...
- **17 Widgets** — ChatBox, AIPanel, ChartView, NumberBall, TaskStatus, ...
- **7 Strategien** — Hot, Cold, Mixed, ML, AI, Ensemble, Avoid
- **AI-Chat** — Claude mit TTS/STT (gTTS + Whisper)
- **i18n** — Deutsch, Persisch, English (1114 Strings)
- **Keyboard-Shortcuts** — Ctrl+R, Escape, Ctrl+C/Del/Ctrl+Z

## Schnellstart

```bash
# Abhaengigkeit installieren
cd ~/lotto/lotto-common && pip install -e . --break-system-packages

# Client starten (LASS-Server muss laufen)
cd ~/lotto/LAS
PYTHONPATH="src:$HOME/lotto/lotto-common/src" python -m lotto_analyzer

# Mit Remote-Server
las --server 192.168.1.100:8049
```

## Verwandte Projekte

| Projekt | Repo | Beschreibung |
|---|---|---|
| **lotto-common** | [Houshang78/lotto-common](https://github.com/Houshang78/lotto-common) | Shared Models, Utils, Config |
| **LASS** | [Houshang78/LASS](https://github.com/Houshang78/LASS) | Server (FastAPI + ML + AI) |

## Lizenz

MIT
