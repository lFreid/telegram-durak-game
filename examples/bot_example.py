"""
Minimal example: a Telegram bot that exposes /durak.

Set environment variables:
    BOT_TOKEN          — token from @BotFather
    DURAK_BACKEND_URL  — e.g. http://127.0.0.1:8765
    DURAK_WEBAPP_URL   — e.g. https://yourdomain.tld/durak  (must be HTTPS)
    ALLOWED_CHAT_ID    — optional, restrict /durak to a single chat

Run:
    python -m examples.bot_example
"""
import os
from telegram.ext import Application

from bot.durak_handler import register_durak_handlers


def main() -> None:
    token       = os.environ["BOT_TOKEN"]
    backend_url = os.environ.get("DURAK_BACKEND_URL", "http://127.0.0.1:8765")
    webapp_url  = os.environ["DURAK_WEBAPP_URL"]
    allowed     = os.environ.get("ALLOWED_CHAT_ID")
    allowed_id  = int(allowed) if allowed else None

    app = Application.builder().token(token).build()
    register_durak_handlers(
        app,
        backend_url=backend_url,
        webapp_url=webapp_url,
        allowed_chat_id=allowed_id,
    )
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
