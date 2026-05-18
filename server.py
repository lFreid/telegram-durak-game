"""
FastAPI WebSocket сервер для игры в Дурака
"""
import asyncio, json, uuid, os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from game import DurakGame, GameType, GameState

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Хранилище сессий в памяти
SESSIONS: dict[str, DurakGame] = {}
# WebSocket подключения: {game_id: {user_id: websocket}}
CONNECTIONS: dict[str, dict[int, WebSocket]] = {}

# ── REST ──────────────────────────────────────────────────────────────────────

@app.post("/api/create")
async def create_game(data: dict):
    game_id = str(uuid.uuid4())[:8].upper()
    gtype = GameType.PEREVODNOJ if data.get("type") == "perevodnoj" else GameType.PODKIDNOY
    SESSIONS[game_id] = DurakGame(game_id, gtype)
    CONNECTIONS[game_id] = {}
    return {"game_id": game_id}

@app.post("/api/join/{game_id}")
async def join_game(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game:
        return {"ok": False, "error": "Игра не найдена"}
    if game.state != GameState.WAITING:
        return {"ok": False, "error": "Игра уже началась"}
    ok = game.add_player(data["user_id"], data["name"])
    if ok:
        await broadcast(game_id, {"type": "player_joined",
                                   "name": data["name"],
                                   "count": len(game.players)})
    return {"ok": ok, "player_count": len(game.players)}

@app.post("/api/start/{game_id}")
async def start_game(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game:
        return {"ok": False, "error": "Игра не найдена"}
    # Установить тип игры если передан
    gtype = data.get("type", "podkidnoy")
    game.game_type = GameType.PEREVODNOJ if gtype == "perevodnoj" else GameType.PODKIDNOY
    ok = game.start()
    if ok:
        await broadcast_state(game_id)
        # Дополнительно уведомить о старте
        await broadcast(game_id, {"type": "game_started"})
    return {"ok": ok}

@app.get("/api/lobby/{game_id}")
async def get_lobby(game_id: str):
    game = SESSIONS.get(game_id)
    if not game:
        return {"ok": False, "error": "Игра не найдена"}
    return {
        "ok": True,
        "state": game.state,
        "players": [{"id": p["id"], "name": p["name"]} for p in game.players],
        "count": len(game.players),
        "game_type": game.game_type,
    }

@app.get("/api/state/{game_id}/{user_id}")
async def get_state(game_id: str, user_id: int):
    game = SESSIONS.get(game_id)
    if not game:
        return {"ok": False, "error": "Игра не найдена"}
    return game.public_state(user_id)


# ── REST эндпоинты для ходов (для тестов и совместимости) ─────────────────

@app.post("/api/attack/{game_id}")
async def rest_attack(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game: return {"ok": False, "error": "Игра не найдена"}
    r = game.attack(data["user_id"], data["card"])
    if r.get("ok"): await broadcast_state(game_id)
    return r

@app.post("/api/defend/{game_id}")
async def rest_defend(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game: return {"ok": False, "error": "Игра не найдена"}
    r = game.defend(data["user_id"], data["attack_idx"], data["card"])
    if r.get("ok"): await broadcast_state(game_id)
    return r

@app.post("/api/take/{game_id}")
async def rest_take(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game: return {"ok": False, "error": "Игра не найдена"}
    r = game.take(data["user_id"])
    if r.get("ok"): await broadcast_state(game_id)
    return r

@app.post("/api/end_turn/{game_id}")
async def rest_end_turn(game_id: str, data: dict):
    game = SESSIONS.get(game_id)
    if not game: return {"ok": False, "error": "Игра не найдена"}
    r = game.end_turn(data["user_id"])
    if r.get("ok"): await broadcast_state(game_id)
    return r

# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{game_id}/{user_id}")
@app.websocket("/durak-ws/{game_id}/{user_id}")
async def websocket_endpoint(ws: WebSocket, game_id: str, user_id: int):
    await ws.accept()
    if game_id not in CONNECTIONS:
        CONNECTIONS[game_id] = {}
    CONNECTIONS[game_id][user_id] = ws

    game = SESSIONS.get(game_id)
    if game:
        await ws.send_text(json.dumps({"type": "state", "data": game.public_state(user_id)}))
        # Уведомить остальных что кто-то подключился (если лобби)
        if game.state == GameState.WAITING:
            player = next((p for p in game.players if p["id"] == user_id), None)
            if player:
                await broadcast(game_id, {"type": "player_joined", "name": player["name"], "count": len(game.players)})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            await handle_action(game_id, user_id, msg)
    except WebSocketDisconnect:
        CONNECTIONS[game_id].pop(user_id, None)

async def handle_action(game_id: str, user_id: int, msg: dict):
    game = SESSIONS.get(game_id)
    if not game:
        return

    action = msg.get("action")
    result = {}
    event = None  # дополнительное событие для анимаций

    if action == "attack":
        result = game.attack(user_id, msg["card"])
        if result.get("ok"):
            event = {"type": "anim", "kind": "attack", "by": user_id, "card": msg["card"]}
    elif action == "defend":
        result = game.defend(user_id, msg["attack_idx"], msg["card"])
        if result.get("ok"):
            event = {"type": "anim", "kind": "defend", "by": user_id, "card": msg["card"],
                     "attack_idx": msg["attack_idx"]}
    elif action == "transfer":
        result = game.transfer(user_id, msg["card"])
        if result.get("ok"):
            event = {"type": "anim", "kind": "transfer", "by": user_id, "card": msg["card"]}
    elif action == "take":
        result = game.take(user_id)
        if result.get("ok"):
            event = {"type": "anim", "kind": "take", "by": user_id}
    elif action == "end_turn":
        result = game.end_turn(user_id)
        if result.get("ok"):
            event = {"type": "anim", "kind": "bito", "by": user_id}

    if result.get("ok"):
        if event:
            await broadcast(game_id, event)
        await broadcast_state(game_id)
    else:
        ws = CONNECTIONS.get(game_id, {}).get(user_id)
        if ws:
            await ws.send_text(json.dumps({"type": "error", "error": result.get("error")}))

# ── Утилиты ───────────────────────────────────────────────────────────────────

async def broadcast(game_id: str, msg: dict):
    dead = []
    for uid, ws in CONNECTIONS.get(game_id, {}).items():
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(uid)
    for uid in dead:
        CONNECTIONS[game_id].pop(uid, None)

async def broadcast_state(game_id: str):
    game = SESSIONS.get(game_id)
    if not game:
        return
    dead = []
    for uid, ws in CONNECTIONS.get(game_id, {}).items():
        try:
            await ws.send_text(json.dumps({"type": "state", "data": game.public_state(uid)}))
        except Exception:
            dead.append(uid)
    for uid in dead:
        CONNECTIONS[game_id].pop(uid, None)

# Статика отдаётся через nginx напрямую из /opt/durak/static
