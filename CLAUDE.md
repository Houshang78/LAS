# LAS — Lotto Analyzer System (GTK4 Desktop Client)

GTK4/Adwaita Desktop-App fuer Lotto 6aus49 und EuroJackpot.
Verbindet sich via REST-API mit dem LASS-Server. Kein lokaler DB-Zugriff.

**Repo**: `Houshang78/LAS`
**Abhaengigkeit**: `lotto-common` (Models, Utils, Config), LASS Server (:8049)

---

## Projektstruktur

```
src/lotto_analyzer/
├── ui/                # GTK4/Adwaita GUI (121 Dateien)
│   ├── app.py         #   GTK Application
│   ├── window.py      #   Hauptfenster + Navigation
│   ├── pages/         #   15 Seiten
│   │   ├── dashboard/ #     Uebersicht, Jackpot, Countdown
│   │   ├── scraper/   #     Daten-Crawling, CSV-Import
│   │   ├── generator/ #     7 Strategien, Batch, ML-Training
│   │   ├── reports/   #     Zyklus-Berichte, Trefferanalyse
│   │   ├── settings/  #     AI/Server Config, Profile
│   │   ├── security/  #     Firewall, Keys, Certs
│   │   ├── server_admin/ # TLS, User, Audit
│   │   └── ...        #     Statistik, Backtest, AI-Chat, DB, Telegram, ...
│   ├── widgets/       #   17 Widgets
│   │   ├── chat_box.py    # Chat-UI (Bubbles, Toolbar)
│   │   ├── ai_panel.py    # AI-Chat (Sessions, Cancel)
│   │   ├── chart_view.py  # Matplotlib in GTK4
│   │   └── ...            # NumberBall, TaskStatus, DaySelector, ...
│   ├── dialogs/       #   Login, Connection, Info
│   ├── locale/        #   i18n (DE/FA/EN, 1114 Strings)
│   └── setup_assistant.py
├── client/            # HTTP/WS Client (15 Dateien)
│   ├── api/           #   APIClient + 10 Mixins (auth, draws, generation, ml, ...)
│   ├── profile_manager.py # Verbindungsprofile
│   ├── ssh_tunnel.py  #   SSH-Tunnel
│   └── ws_client.py   #   WebSocket Client
└── __main__.py        # Entry: las [--server HOST:PORT]
```

---

## Architektur-Regeln

- **GUI = reine Praesentationsschicht** — zeigt Daten an, nimmt Eingaben entgegen
- **Kein ML/AI/Statistik-Code** — kein torch, sklearn, numpy, kein direkter DB-Zugriff
- **Alles via REST-API** — alle Daten kommen vom LASS-Server (httpx)
- **Login-Pflicht** — ohne Anmeldung keine Seite mit Daten
- **Dateigroesse max 500 Zeilen** — Klassen in Packages mit Mixins aufteilen
- **BasePage** — alle 15 Seiten erben von BasePage (Timer, Lock, Cancel, ReadOnly, Stale-Check)
- **Safe Worker** — Exception im Thread → immer `GLib.idle_add(cleanup)`
- **Cancel-Event** — `threading.Event()` fuer Thread-Abbruch

---

## UI-Seiten (15)

| Seite | Beschreibung |
|---|---|
| **Dashboard** | Ziehungen, Integritaet, Jackpot, Countdown, Strategie-Performance |
| **Daten-Crawler** | Web-Crawling, CSV-Import, manuelle Eingabe |
| **Statistik** | 18 Analyse-Methoden, Charts, CSV-Export, AI-Kommentar |
| **Generator** | 7+2 Strategien, Near-Duplicate-Schutz, "Warum?"-Erklaerungen |
| **Berichte** | Zyklus-Berichte, Trefferanalyse, gekaufte Tipps, Telegram, Markdown-Export |
| **Qualitaet** | 4 Charts (Trefferquote, Verteilung, Strategien, ML-Loss) |
| **Backtest** | Walk-Forward, 9 Strategien, Feature-Importance |
| **AI-Chat** | Claude-Chat (AIPanel), TTS/STT, Session-Verwaltung |
| **Schein-Pruefung** | Tipp pruefen, Gewinn-Rechner |
| **Datenbank** | DB-Browser, CRUD, Undo-Delete, Bulk-Edit, Copy-to-Clipboard |
| **Telegram** | Bot-Login/Logout, QR-Code, /buy, Nachrichtenverlauf |
| **Einstellungen** | AI-Config, Server-Config, Profile, Theme, Audio |
| **Sicherheit** | Firewall, API-Keys, SSH-Schluessel, Zertifikate |
| **Monitor** | Live-Aktivitaet, Scheduler-Status, 9 Zyklus-Toggles |
| **Server** | TLS, Benutzerverwaltung, Audit-Log, systemd |

---

## Widget-Architektur

| Widget | Beschreibung |
|---|---|
| `chat_box.py` | Chat-UI (Bubbles + Toolbar + Scroll + Mic + Speaker) |
| `ai_panel.py` | ChatBox + AI-Logik (Sessions, History, Cancel) — 9 Seiten |
| `speak_button.py` | TTS (gTTS + GStreamer) |
| `mic_button.py` | STT (Whisper) |
| `chart_view.py` | Matplotlib in GTK4 |
| `task_status.py` | Polling-Bar fuer laufende Tasks |

---

## API-Client

APIClient mit 10 Mixins verbindet sich zum LASS-Server:

- **AuthMixin** — Login (Passwort, SSH-Key, Cert), Token-Refresh, 2FA
- **DrawsMixin** — Ziehungen abrufen, CSV-Import, manuelle Eingabe
- **GenerationMixin** — Generate, Batch, Combos, Auto-Trigger
- **PredictionsMixin** — Predictions abrufen, kaufen, AI-analysieren
- **MLMixin** — Training, Hypersearch, Tournament, Self-Improve
- **SettingsMixin** — Config lesen/schreiben
- **TelegramMixin** — Bot-Status, QR-Login, Nachrichten
- **AdminMixin** — Users, Audit-Log, API-Keys

---

## Tech-Stack

| Bereich | Technologie |
|---|---|
| GUI | GTK4 + Libadwaita (gi) |
| HTTP | httpx (async-faehig) |
| Charts | matplotlib (eingebettet in GTK4) |
| Audio | gTTS (TTS) + OpenAI Whisper (STT) + GStreamer |
| i18n | gettext (DE/FA/EN, 1114 Strings) |

---

## Betrieb

```bash
las                                 # Default: localhost:8049
las --server 192.168.1.100:8049    # Remote-Server
las --debug                         # Debug-Modus

# Oder ohne Installation
PYTHONPATH="src:$HOME/lotto/lotto-common/src" python -m lotto_analyzer
```

## Verwandte Projekte

| Projekt | Repo | Beschreibung |
|---|---|---|
| **lotto-common** | `Houshang78/lotto-common` | Shared Models, Utils, Config |
| **LASS** | `Houshang78/LASS` | Server (FastAPI + ML + AI) |
| **LASS-Portal** | `Houshang78/LASS-Portal` | Web Login/Dashboard |
