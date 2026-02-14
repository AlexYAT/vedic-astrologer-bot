"""Команды /tomorrow, /topics, /favorable, /contact, /setdata."""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import assistant
import db
from handlers.common import (
    format_assistant_response_for_telegram,
    get_main_menu_keyboard,
    get_topics_keyboard,
    get_topic_label,
    validate_email,
)
from handlers.start import STATE_BIRTH_DATE

logger = logging.getLogger(__name__)

MSG_NEED_DATA = (
    "Для получения прогноза необходимо заполнить данные рождения. "
    "Отправь /start или /setdata для ввода."
)


def format_user_data_for_prompt(user: dict) -> str:
    """Формирование строки с данными пользователя для промпта ассистенту."""
    parts = [
        f"Дата рождения: {user.get('birth_date', 'не указана')}",
        f"Время рождения: {user.get('birth_time', 'не указано')}",
        f"Место рождения: {user.get('birth_place', 'не указано')}",
    ]
    return "\n".join(parts)


async def ask_assistant_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
) -> None:
    """
    Отправить запрос ассистенту, показать «печатает» и ответить пользователю.
    Обрабатывает ошибки.
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    try:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        response = assistant.send_message_and_get_response(user.id, user_message)
        response = format_assistant_response_for_telegram(response)
        await update.message.reply_text(response, parse_mode="HTML")
    except Exception as e:
        logger.exception("Ошибка при обращении к ассистенту: %s", e)
        await update.message.reply_text(
            "К сожалению, произошла ошибка при получении ответа. Попробуй позже."
        )


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прогноз на завтрашний день."""
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return

    user_data = db.get_user(user.id)
    data_str = format_user_data_for_prompt(user_data)
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        "Сделай персонализированный прогноз на завтрашний день для этого человека."
    )
    await ask_assistant_and_reply(update, context, message)


async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вывод инлайн-клавиатуры с темами."""
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return

    await update.message.reply_text(
        "Выбери тему для персонализированного прогноза:",
        reply_markup=get_topics_keyboard(),
    )


async def topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка выбора темы из инлайн-клавиатуры."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await query.edit_message_text(MSG_NEED_DATA)
        return

    topic_label = get_topic_label(query.data)
    if not topic_label:
        return

    user_data = db.get_user(user.id)
    data_str = format_user_data_for_prompt(user_data)
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        f"Дай персонализированный прогноз по теме «{topic_label}» для этого человека."
    )

    # Используем edit_message_text для ответа — т.к. callback, update.message может быть None
    try:
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        response = assistant.send_message_and_get_response(user.id, message)
        response = format_assistant_response_for_telegram(response)
        await query.edit_message_text(response, parse_mode="HTML")
    except Exception as e:
        logger.exception("Ошибка при обращении к ассистенту: %s", e)
        await query.edit_message_text(
            "К сожалению, произошла ошибка. Попробуй позже."
        )


async def favorable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ближайшие благоприятные дни для начинаний."""
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return

    user_data = db.get_user(user.id)
    data_str = format_user_data_for_prompt(user_data)
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        "Рекомендуй ближайшие благоприятные дни для важных начинаний с учётом его гороскопа."
    )
    await ask_assistant_and_reply(update, context, message)


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрос на обновление контактных данных."""
    user = update.effective_user
    if not user:
        return

    current = db.get_user(user.id)
    phone = current.get("phone") if current else None
    email = current.get("email") if current else None

    text = "Текущие контактные данные:\n"
    text += f"Телефон: {phone or 'не указан'}\n"
    text += f"Email: {email or 'не указан'}\n\n"
    text += (
        "Отправь сообщение в формате:\n"
        "Телефон: +7...\n"
        "Email: example@mail.com\n\n"
        "Можно указать только один из параметров или «пропустить»."
    )
    context.user_data["awaiting_contact"] = True
    await update.message.reply_text(text)


async def setdata_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Повторный ввод или изменение всех данных. Запускает сценарий сбора данных."""
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    db.create_user(user.id)
    await update.message.reply_text(
        "Сейчас обновим твои данные. Введи дату рождения в формате ДД.ММ.ГГГГ (например, 15.03.1990):"
    )
    return STATE_BIRTH_DATE


async def contact_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода контактных данных после /contact.
    Вызывается только когда awaiting_contact=True (иначе сообщение игнорируется).
    """
    if not context.user_data.get("awaiting_contact"):
        return
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    context.user_data["awaiting_contact"] = False

    phone = None
    email = None

    if text in ("пропустить", "skip", "-"):
        await update.message.reply_text("Контактные данные не изменены.")
        return

    # Парсим формат "Телефон: X" и "Email: Y"
    for line in text.split("\n"):
        line = line.strip()
        if line.lower().startswith("телефон:"):
            phone = line.split(":", 1)[1].strip() or None
        elif line.lower().startswith("email:"):
            raw_email = line.split(":", 1)[1].strip() or None
            if raw_email and validate_email(raw_email):
                email = raw_email
            elif raw_email:
                await update.message.reply_text(
                    "Неверный формат email. Введите корректный адрес или «пропустить»."
                )
                context.user_data["awaiting_contact"] = True
                return

    if not phone and not email:
        # Пробуем распознать как один параметр
        if "@" in text:
            if validate_email(text):
                email = text
            else:
                await update.message.reply_text("Неверный формат email.")
                context.user_data["awaiting_contact"] = True
                return
        else:
            phone = text if text else None

    updates = {}
    if phone is not None:
        updates["phone"] = phone
    if email is not None:
        updates["email"] = email
    if updates:
        db.update_user(user.id, **updates)
    await update.message.reply_text("Контактные данные обновлены.")
