"""Application entry point (polling). Run: python -m bot.main"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import config, db, handlers

log = logging.getLogger("bot")


def build_app() -> Application:
    token = config.require("TELEGRAM_TOKEN")
    group_id = int(config.require("ORGANISER_GROUP_ID"))

    app = Application.builder().token(token).build()
    app.bot_data["db"] = db.connect()
    app.bot_data["organiser_group_id"] = group_id

    private = filters.ChatType.PRIVATE
    group = filters.Chat(chat_id=group_id)

    app.add_handler(CommandHandler("start", handlers.start, filters=private))
    app.add_handler(CommandHandler("human", handlers.open_human, filters=private))
    app.add_handler(CommandHandler("end", handlers.end_ticket, filters=private))
    app.add_handler(CallbackQueryHandler(handlers.open_human, pattern=f"^{handlers.HUMAN_CALLBACK}$"))
    app.add_handler(CommandHandler("close", handlers.close_ticket, filters=group))
    app.add_handler(MessageHandler(private & ~filters.COMMAND, handlers.private_message))
    app.add_handler(
        MessageHandler(group & ~filters.COMMAND & ~filters.StatusUpdate.ALL, handlers.organiser_message)
    )
    app.add_error_handler(handlers.on_error)
    return app


def log_model() -> None:
    model = config.LLM_MODEL
    log.info("active model=%s fallback=%s", model, config.LLM_FALLBACK_MODEL or "none")
    if model.endswith(":free"):
        log.warning("running on the free model; switch LLM_MODEL for event days")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs every request URL, and the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log_model()
    build_app().run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
