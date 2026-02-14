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
    validate_email,
)

logger = logging.getLogger(__name__)

# Состояния ConversationHandler
STATE_BIRTH_DATE = 1
STATE_BIRTH_TIME = 2
STATE_BIRTH_PLACE = 3
STATE_PHONE = 4
STATE_EMAIL = 5


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
    """Получение места рождения."""
    place = update.message.text.strip()
    if not place:
        await update.message.reply_text("Введи название города и страны:")
        return STATE_BIRTH_PLACE

    context.user_data["birth_place"] = place
    await update.message.reply_text(
        "Телефон (опционально). Введи номер или отправь «пропустить»:"
    )
    return STATE_PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение телефона (опционально)."""
    text = update.message.text.strip().lower()
    if text in ("пропустить", "skip", "-", ""):
        context.user_data["phone"] = None
    else:
        context.user_data["phone"] = text

    await update.message.reply_text(
        "Email (опционально). Введи адрес или отправь «пропустить»:"
    )
    return STATE_EMAIL


async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение email (опционально) и сохранение всех данных."""
    text = update.message.text.strip().lower()
    if text in ("пропустить", "skip", "-", ""):
        context.user_data["email"] = None
    else:
        if not validate_email(text):
            await update.message.reply_text("Неверный формат email. Введи корректный адрес или «пропустить»:")
            return STATE_EMAIL
        context.user_data["email"] = text

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    db.save_user_data(
        user_id=user.id,
        birth_date=context.user_data["birth_date"],
        birth_time=context.user_data["birth_time"],
        birth_place=context.user_data["birth_place"],
        phone=context.user_data.get("phone"),
        email=context.user_data.get("email"),
    )

    await update.message.reply_text(
        "Данные успешно сохранены! Теперь ты можешь получать персонализированные прогнозы. "
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена сбора данных."""
    context.user_data.clear()
    await update.message.reply_text("Регистрация отменена. Отправь /start, чтобы начать заново.")
    return ConversationHandler.END
