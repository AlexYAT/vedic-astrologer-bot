"""Команда /start и сбор данных пользователя."""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import db
from handlers.common import (
    get_main_menu_keyboard,
    get_user_display_name,
    validate_birth_date,
    validate_birth_time,
)

logger = logging.getLogger(__name__)

# Состояния ConversationHandler (только дата, время, место рождения)
STATE_BIRTH_DATE = 1
STATE_BIRTH_TIME = 2
STATE_BIRTH_PLACE = 3


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Обработка /start.
    Если данные есть — показываем меню. Иначе — запускаем сбор данных.
    """
    user = update.effective_user
    if not user:
        return None

    user_id = user.id
    db.create_user(user_id)

    display_name = get_user_display_name(user)

    if db.user_has_full_data(user_id):
        await update.message.reply_text(
            f"Привет, {display_name}! Рад снова тебя видеть. "
            "Твои данные уже сохранены. Выбери команду из меню ниже:",
            reply_markup=get_main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"Привет, {display_name}! Я — Ведический астролог, твой персональный советник по Джйотишу.\n\n"
        "Для персонализированных прогнозов мне нужны твои данные рождения.\n"
        "Введи дату рождения в формате ДД.ММ.ГГГГ (например, 15.03.1990):"
    )
    return STATE_BIRTH_DATE


async def receive_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение и валидация даты рождения."""
    text = update.message.text.strip()
    if not validate_birth_date(text):
        await update.message.reply_text(
            "Неверный формат. Введи дату в формате ДД.ММ.ГГГГ (например, 15.03.1990):"
        )
        return STATE_BIRTH_DATE

    context.user_data["birth_date"] = text
    await update.message.reply_text("Отлично! Теперь введи время рождения в формате ЧЧ:ММ (например, 14:30):")
    return STATE_BIRTH_TIME


async def receive_birth_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение и валидация времени рождения."""
    text = update.message.text.strip()
    if not validate_birth_time(text):
        await update.message.reply_text(
            "Неверный формат. Введи время в формате ЧЧ:ММ (например, 14:30):"
        )
        return STATE_BIRTH_TIME

    context.user_data["birth_time"] = text
    await update.message.reply_text("Спасибо! Теперь введи место рождения (город, страна):")
    return STATE_BIRTH_PLACE


async def receive_birth_place(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение места рождения и сохранение данных (контакты не собираем)."""
    place = update.message.text.strip()
    if not place:
        await update.message.reply_text("Введи название города и страны:")
        return STATE_BIRTH_PLACE

    context.user_data["birth_place"] = place
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    db.save_user_data(
        telegram_id=user.id,
        birth_date=context.user_data["birth_date"],
        birth_time=context.user_data["birth_time"],
        birth_place=context.user_data["birth_place"],
        phone=None,
        email=None,
    )
    row = db.get_user(user.id)
    if row and row.get("id"):
        db.log_user_request(row["id"], "setdata", None, success=1, response_time_ms=None)

    await update.message.reply_text(
        "Данные успешно сохранены! Теперь ты можешь получать персонализированные прогнозы. "
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def setdata_callback_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вход в сценарий смены данных по нажатию инлайн-кнопки «Изменить данные»."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Введи дату рождения в формате ДД.ММ.ГГГГ (например, 15.03.1990):",
    )
    return STATE_BIRTH_DATE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена сбора данных."""
    context.user_data.clear()
    await update.message.reply_text(
        "Регистрация отменена. Отправь /start или /menu.",
        reply_markup=get_main_menu_keyboard(),
    )
    return ConversationHandler.END
