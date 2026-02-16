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

from utils.logging_setup import setup_logging

import assistant
import config
import db
from version import __version__
from handlers.commands import (
    cta_full_access_callback,
    check_action_message,
    favorable_command,
    menu_button_handler,
    menu_command,
    my_data_command,
    setdata_command,
    today_forecast_command,
    topic_callback,
    topics_command,
    tomorrow_forecast_command,
)
from handlers.start import (
    cancel,
    receive_birth_date,
    receive_birth_place,
    receive_birth_time,
    setdata_callback_entry,
    start_command,
    STATE_BIRTH_DATE,
    STATE_BIRTH_PLACE,
    STATE_BIRTH_TIME,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Запуск бота."""
    setup_logging()
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
            MessageHandler(
                filters.Regex("^Изменить данные$"),
                setdata_command,
            ),
            CallbackQueryHandler(setdata_callback_entry, pattern="^action_setdata$"),
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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application = Application.builder().token(token).build()

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_forecast_command))
    application.add_handler(CommandHandler("topics", topics_command))
    application.add_handler(CommandHandler("favorable", favorable_command))
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(
                "^(🔮 Сегодня|🔮 Завтра|❓ Проверить действие|📅 Удачный день|🎯 По теме|⚙️ Мои данные)$"
            ),
            menu_button_handler,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, check_action_message)
    )
    application.add_handler(CallbackQueryHandler(topic_callback, pattern=r"^topic_"))
    application.add_handler(
        CallbackQueryHandler(cta_full_access_callback, pattern="^cta_full_access$")
    )

    logger.info("Vedic Astrologer Bot v%s starting...", __version__)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
