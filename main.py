"""Точка входа: запуск бота «Ведический астролог»."""

import logging
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import assistant
import config
import db
from handlers.commands import (
    contact_command,
    contact_update_handler,
    favorable_command,
    setdata_command,
    topic_callback,
    topics_command,
    tomorrow_command,
)
from handlers.start import (
    cancel,
    receive_birth_date,
    receive_birth_place,
    receive_birth_time,
    receive_email,
    receive_phone,
    start_command,
    STATE_BIRTH_DATE,
    STATE_BIRTH_PLACE,
    STATE_BIRTH_TIME,
    STATE_EMAIL,
    STATE_PHONE,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Запуск бота."""
    token = config.get_telegram_token()
    api_key = config.get_openai_api_key()
    assistant_id = config.get_assistant_id()
    db_path = config.get_db_path()

    db.init_db(db_path)
    assistant.init_assistant(api_key, assistant_id)

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("setdata", setdata_command),
        ],
        states={
            STATE_BIRTH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_birth_date),
            ],
            STATE_BIRTH_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_birth_time),
            ],
            STATE_BIRTH_PLACE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_birth_place),
            ],
            STATE_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone),
            ],
            STATE_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application = Application.builder().token(token).build()

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("topics", topics_command))
    application.add_handler(CommandHandler("favorable", favorable_command))
    application.add_handler(CommandHandler("contact", contact_command))
    application.add_handler(CallbackQueryHandler(topic_callback, pattern=r"^topic_"))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            contact_update_handler,
        )
    )

    logger.info("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
