# 🃏 Telegram Durak Game

> Multiplayer **Дурак** (Russian "Fool" card game — Подкидной & Переводной) as a **Telegram Mini App**.
> FastAPI + WebSockets backend, drag-and-drop HTML5 frontend, native Telegram WebApp launcher via [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot).

![version](https://img.shields.io/badge/version-1.0-blue) ![python](https://img.shields.io/badge/python-3.10%2B-brightgreen) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## ✨ Features

- 🎮 **2–3 players**, real-time state sync via WebSocket.
- 🇷🇺 Both classic Russian variants: **Подкидной** (basic) & **Переводной** (with pass-on).
- 📲 **Native Telegram Mini App** — opens inside the Telegram client (no external browser), full `Telegram.WebApp` SDK integration (theme colors, expand, haptic feedback, close confirmation).
- 🎨 Polished green felt UI with **animated card flight, opponent card fans, deck pile with trump card under it**, sortable hand with fan layout, confetti on victory.
- 🖱️ **Drag & drop** on desktop, **touch drag with floating clone** on mobile.
- 🔁 Auto-reconnect WebSocket, broadcast events for attack/defend/take/«bito».
- 🔒 Optional `allowed_chat_id` gate so `/durak` only works in your private group.
- 🛟 DM fallback via deep-link (`t.me/<bot>?start=durak_<id>_<role>`) when the user hasn't started the bot privately yet.

## 🏗️ Architecture

```
┌────────────────┐   /durak    ┌──────────────────┐  WebApp btn   ┌────────────────────┐
│ Telegram group │ ─────────▶ │ python-telegram- │ ─────────────▶│   Telegram client  │
│   (users)      │            │      bot         │               │ opens Mini App URL │
└────────────────┘            └────────┬─────────┘               └─────────┬──────────┘
                                       │ POST /api/create                  │
                                       ▼                                   │ wss://…/durak-ws
                              ┌──────────────────┐                         │
                              │  FastAPI server  │ ◀───────────────────────┘
                              │   (server.py)    │
                              │ WS  /durak-ws/…  │
                              │ REST /api/…      │
                              └──────────────────┘
                                       │
                              ┌──────────────────┐
                              │ Game logic (pure │
                              │   game.py)       │
                              └──────────────────┘
```

## 📁 Layout

```
.
├── server.py                  # FastAPI app: REST + WebSocket
├── game.py                    # Pure game logic (no I/O)
├── static/
│   └── index.html             # Mini App frontend (single-file, no build step)
├── bot/
│   ├── __init__.py
│   └── durak_handler.py       # Drop-in handlers for python-telegram-bot
├── examples/
│   └── bot_example.py         # Minimal example bot wiring
├── deploy/
│   ├── durak-game.service     # systemd unit for the backend
│   └── nginx.conf.example     # nginx reverse-proxy + static template
├── requirements.txt
├── LICENSE
└── README.md
```

## 🚀 Quick start (local dev)

```bash
git clone https://github.com/lFreid/telegram-durak-game.git
cd telegram-durak-game

python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1) Start the FastAPI backend
uvicorn server:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/api/lobby/TEST> in another terminal to confirm it answers (404 for an unknown id is fine).

For the **frontend**, Telegram requires HTTPS in production. For local UI testing only, you can serve `static/index.html` with any static server:

```bash
python -m http.server -d static 8080
# then open http://127.0.0.1:8080/?game_id=ABCD1234&user_id=1&name=Alice&host=1
```

> ⚠️ Real Telegram Mini App testing requires a **publicly reachable HTTPS URL**. See **Production deployment** below.

## 🤖 Wiring the Telegram bot

`bot/durak_handler.py` is a drop-in module — register it into your existing `Application`:

```python
from telegram.ext import Application
from bot.durak_handler import register_durak_handlers

app = Application.builder().token(BOT_TOKEN).build()
register_durak_handlers(
    app,
    backend_url="http://127.0.0.1:8765",          # FastAPI base
    webapp_url="https://yourdomain.tld/durak",    # public Mini App URL (HTTPS)
    allowed_chat_id=-1001234567890,               # optional: lock to a single group
)
app.run_polling(allowed_updates=["message", "callback_query"])
```

This adds:

- `/durak` — creates a session and posts **👑 Host** / **🎮 Join** inline buttons.
- Callback handler — sends each player a private DM with a `WebAppInfo` button that opens the game inside Telegram.
- `/start` deep-link payload `durak_<game_id>_<h|p>` for the DM-fallback path.

A complete runnable example is in `examples/bot_example.py`.

## 🌐 Production deployment

### 1. Backend service

```bash
sudo useradd -r -s /sbin/nologin durak
sudo mkdir -p /opt/durak /opt/durak-venv
sudo cp -r server.py game.py static /opt/durak/
sudo python3 -m venv /opt/durak-venv
sudo /opt/durak-venv/bin/pip install -r requirements.txt
sudo chown -R durak:durak /opt/durak /opt/durak-venv

sudo cp deploy/durak-game.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now durak-game
```

### 2. nginx (HTTPS terminator)

Adapt `deploy/nginx.conf.example`, swap in your domain & certificate, then:

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/durak
sudo ln -s /etc/nginx/sites-available/durak /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

The config exposes:

| Path           | Target                       |
|----------------|------------------------------|
| `/api/*`       | `127.0.0.1:8765` (REST)      |
| `/durak-ws/*`  | `127.0.0.1:8765` (WebSocket) |
| `/durak`       | `static/` (Mini App HTML)    |

### 3. Telegram bot

Run your bot (with `register_durak_handlers` wired up) as a long-running service — see `examples/bot_example.py` or your own systemd unit.

> **Important:** the path `/durak-ws/{game_id}/{user_id}` and `/api/*` are both served by the same FastAPI app — make sure nginx proxies **both** prefixes to `127.0.0.1:8765`, including the WebSocket `Upgrade` headers. Mis-routing the WS path is the single most common reason the lobby works but in-game state goes dead.

## 🎯 REST & WebSocket API

| Method | Path                                | Body / Notes                                |
|-------:|-------------------------------------|---------------------------------------------|
| `POST` | `/api/create`                       | `{}` → `{game_id}`                          |
| `POST` | `/api/join/{game_id}`               | `{user_id, name}`                           |
| `POST` | `/api/start/{game_id}`              | `{user_id, type: "podkidnoy"\|"perevodnoj"}`|
| `GET`  | `/api/lobby/{game_id}`              | players + state                             |
| `GET`  | `/api/state/{game_id}/{user_id}`    | full state from viewer's POV                |
| `WS`   | `/durak-ws/{game_id}/{user_id}`     | bidirectional game channel                  |

WebSocket client messages:

```jsonc
{ "action": "attack",   "card": "10♠" }
{ "action": "defend",   "attack_idx": 0, "card": "J♠" }
{ "action": "transfer", "card": "10♥" }      // переводной only
{ "action": "take" }                          // defender gives up
{ "action": "end_turn" }                      // attacker calls "bito"
```

Server pushes:

```jsonc
{ "type": "state",         "data": { ... full state ... } }
{ "type": "error",         "error": "Карта не бьёт" }
{ "type": "anim",          "kind": "attack|defend|transfer|take|bito", "by": <user_id>, "card": "..." }
{ "type": "player_joined", "name": "Alice", "count": 2 }
{ "type": "game_started"  }
```

## 🛠️ Customisation hints

- **Theme** — `body { background: ... }` in `static/index.html` controls the felt color.
- **Card faces** — Unicode-only right now; swap `makeCard()` for SVG/PNG sprites if you want pretty pips.
- **Max players** — `DurakGame.MAX_PLAYERS = 3` in `game.py`.
- **Hand size** — change `< 6` in `DurakGame._refill()`.
- **State store** — in-memory `SESSIONS` dict; swap for Redis if you need horizontal scaling.

## 🧪 Tested with

- Python 3.11 / 3.12
- `python-telegram-bot` 21.x
- `fastapi` 0.110+, `uvicorn[standard]` 0.27+
- iOS / Android / desktop Telegram clients

## 📜 License

MIT — see `LICENSE`.

## 🙌 Credits

Built as a Mini App for a private Telegram community and released as v1.0 for anyone who wants a clean, hackable Durak base.
