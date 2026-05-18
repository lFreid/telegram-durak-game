"""
Telegram Durak — drop-in handlers for python-telegram-bot.

Adds two pieces of functionality to your bot:

1. /durak  — creates a new game session via the FastAPI backend and posts
   two inline buttons in the chat: 👑 Host (only the creator) and 🎮 Join.
2. /start  — supports a deep-link payload `durak_<game_id>_<h|p>` so users
   coming from the group's "Open in DM" fallback receive a private WebApp
   button.

Buttons open the game as a native Telegram Mini App (WebAppInfo). If a
player has not started the bot in DM yet, a deep-link fallback is sent
into the group so they can open the bot and the Mini App from there.

Usage example (see `examples/bot_example.py` for a full working app):

    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from bot.durak_handler import register_durak_handlers

    app = Application.builder().token(BOT_TOKEN).build()
    register_durak_handlers(
        app,
        backend_url="http://127.0.0.1:8765",   # FastAPI base URL
        webapp_url="https://example.com/durak", # public HTTPS URL of the Mini App
        allowed_chat_id=ALLOWED_CHAT,           # optional: restrict /durak to one chat
    )
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class DurakConfig:
    backend_url: str           # e.g. http://127.0.0.1:8765
    webapp_url: str            # e.g. https://example.com/durak (must be HTTPS for Telegram WebApp)
    allowed_chat_id: Optional[int] = None  # restrict /durak to this chat, None = any chat


_CONFIG: Optional[DurakConfig] = None


def _cfg() -> DurakConfig:
    if _CONFIG is None:
        raise RuntimeError("Call register_durak_handlers(...) first.")
    return _CONFIG


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_game_session() -> str:
    """POST /api/create on the FastAPI backend, return game_id."""
    req = urllib.request.Request(
        f"{_cfg().backend_url}/api/create",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["game_id"]


def _webapp_kb(game_id: str, user_id: int, name: str, is_host: bool) -> InlineKeyboardMarkup:
    """Build an inline keyboard that opens the game as a Telegram Mini App."""
    url = (
        f"{_cfg().webapp_url}/"
        f"?game_id={game_id}&user_id={user_id}"
        f"&name={urllib.parse.quote(name or 'Player')}"
        f"&host={'1' if is_host else '0'}"
    )
    label = "👑 Open game (host)" if is_host else "🃏 Open game"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, web_app=WebAppInfo(url=url))]])


async def _send_webapp_to_user(ctx: ContextTypes.DEFAULT_TYPE, user, game_id: str, is_host: bool) -> bool:
    """Try to DM the user the WebApp button. Returns False if DM is closed."""
    kb = _webapp_kb(game_id, user.id, user.first_name or "Player", is_host)
    role = "👑 You are the host" if is_host else "🎮 You joined"
    try:
        await ctx.bot.send_message(
            chat_id=user.id,
            text=f"{role} of game <code>{game_id}</code>\n\nTap below to open the table inside Telegram 👇",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return True
    except Exception:
        return False


# ── /durak ────────────────────────────────────────────────────────────────────

async def cmd_durak(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a Durak game and post Host/Join buttons in the chat."""
    cfg = _cfg()
    chat = update.effective_chat
    if cfg.allowed_chat_id is not None and chat.id != cfg.allowed_chat_id:
        await update.message.reply_text("❌ /durak is not enabled in this chat.")
        return

    try:
        game_id = _create_game_session()
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to create game: {e}")
        return

    creator = update.effective_user
    ctx.bot_data.setdefault("durak_creators", {})[game_id] = creator.id

    text = (
        f"🃏 <b>Durak game!</b>\n\n"
        f"🆔 Code: <code>{game_id}</code>\n"
        f"👑 Host: {creator.first_name}\n\n"
        f"👇 Tap your button:"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Host (creator only)", callback_data=f"durak_host:{game_id}")],
        [InlineKeyboardButton("🎮 Join as player",      callback_data=f"durak_join:{game_id}")],
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


# ── Inline button callbacks ───────────────────────────────────────────────────

async def cb_durak(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Host/Join button presses."""
    cfg = _cfg()
    q = update.callback_query
    user = q.from_user

    if cfg.allowed_chat_id is not None and q.message.chat.id != cfg.allowed_chat_id:
        await q.answer("❌ Not in this chat", show_alert=True)
        return

    data = q.data or ""
    if ":" not in data:
        await q.answer()
        return
    action, game_id = data.split(":", 1)

    creator_id = ctx.bot_data.get("durak_creators", {}).get(game_id)

    if action == "durak_host":
        if user.id != creator_id:
            await q.answer("Only the creator can press this.", show_alert=True)
            return
        is_host = True
    else:  # durak_join
        if user.id == creator_id:
            await q.answer("You are the creator — tap 👑 Host", show_alert=True)
            return
        is_host = False

    # Try to send the Mini App button into DM
    ok = await _send_webapp_to_user(ctx, user, game_id, is_host)
    if ok:
        await q.answer("Check your DM 📩")
        await q.message.reply_text(
            ("👑 " if is_host else "🎮 ") + f"{user.first_name} joined the game"
        )
        return

    # Fallback: deep-link the user to /start in DM
    bot_me = await ctx.bot.get_me()
    role_code = "h" if is_host else "p"
    deeplink = f"https://t.me/{bot_me.username}?start=durak_{game_id}_{role_code}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📩 Open in DM", url=deeplink)]])
    await q.answer()
    await q.message.reply_text(
        f"{user.first_name}, open the bot in DM to play inside Telegram 👇",
        reply_markup=kb,
    )


# ── /start with deep-link support ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start, including deep-link payload `durak_<game_id>_<h|p>`."""
    args = ctx.args or []
    user = update.effective_user
    chat = update.effective_chat

    if args and args[0].startswith("durak_"):
        parts = args[0].split("_")
        if len(parts) >= 3:
            game_id = parts[1]
            is_host = parts[2] == "h"
            kb = _webapp_kb(game_id, user.id, user.first_name or "Player", is_host)
            role = "👑 Host" if is_host else "🎮 Player"
            await update.message.reply_text(
                f"{role} of game <code>{game_id}</code>\n\nTap below 👇",
                parse_mode="HTML",
                reply_markup=kb,
            )
            return

    if chat.type == "private":
        await update.message.reply_text(
            "Hi! I host the multiplayer Durak game.\n"
            "Use /durak in a group to create a new table."
        )


# ── Public registration helper ────────────────────────────────────────────────

def register_durak_handlers(
    app: Application,
    *,
    backend_url: str,
    webapp_url: str,
    allowed_chat_id: Optional[int] = None,
    register_start: bool = True,
) -> None:
    """Wire up Durak handlers into an existing python-telegram-bot Application.

    Args:
        app: the Application instance.
        backend_url: base URL of the FastAPI backend (server.py), e.g. http://127.0.0.1:8765.
        webapp_url: public HTTPS URL of the Mini App (where index.html is served from).
        allowed_chat_id: if set, /durak only works in this chat; None = any chat.
        register_start: also register /start with deep-link handling (set False if your
            bot already owns /start, then call cmd_start() yourself from there).
    """
    global _CONFIG
    _CONFIG = DurakConfig(
        backend_url=backend_url.rstrip("/"),
        webapp_url=webapp_url.rstrip("/"),
        allowed_chat_id=allowed_chat_id,
    )

    app.add_handler(CommandHandler("durak", cmd_durak))
    app.add_handler(CallbackQueryHandler(cb_durak, pattern=r"^durak_(host|join):"))
    if register_start:
        app.add_handler(CommandHandler("start", cmd_start))
