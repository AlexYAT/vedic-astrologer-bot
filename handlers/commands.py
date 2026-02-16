"""Команды: Сегодня/Завтра, Проверить действие, Удачный день, По теме, Мои данные; /menu, /setdata."""

import logging
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import action_validation
import assistant
import db
import openai_safe
from handlers.common import (
    CTA_TEXT,
    format_assistant_response_for_telegram,
    get_cta_keyboard,
    get_main_menu_keyboard,
    get_topics_keyboard,
    get_topic_label,
    MENU_TEXT_TO_COMMAND,
)
from handlers.start import STATE_BIRTH_DATE

EXAMPLES_ACTION = "Пример: подписать договор, подать заявление, поговорить с руководителем."

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


async def _send_service_unavailable(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None
) -> None:
    """Отправить сообщение о недоступности сервиса и показать главное меню."""
    target = chat_id or (update.effective_chat.id if update.effective_chat else None)
    if target is None:
        return
    await context.bot.send_message(
        chat_id=target,
        text=openai_safe.MSG_SERVICE_UNAVAILABLE,
        reply_markup=get_main_menu_keyboard(),
    )


async def _send_run_timeout(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None
) -> None:
    """Ответ готовится дольше обычного: сообщение и меню (новый run не создаём)."""
    target = chat_id or (update.effective_chat.id if update.effective_chat else None)
    if target is None:
        return
    await context.bot.send_message(
        chat_id=target,
        text=openai_safe.MSG_RUN_TIMEOUT,
        reply_markup=get_main_menu_keyboard(),
    )


async def _send_cta(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None) -> None:
    """Отправить CTA-блок (текст + кнопка «Полный доступ») после ответа ассистента."""
    target = chat_id or (update.effective_chat.id if update.effective_chat else None)
    if target is None:
        return
    await context.bot.send_message(
        chat_id=target,
        text=CTA_TEXT,
        reply_markup=get_cta_keyboard(),
    )


async def ask_assistant_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
    request_type: str,
    request_text: str | None = None,
) -> None:
    """
    Отправить запрос ассистенту, показать ответ и CTA-блок.
    При timeout или ошибке API — сообщение о недоступности и меню.
    Логирует запрос в user_requests (request_type, success, response_time_ms).
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    row = db.get_user(user.id)
    internal_user_id = row.get("id")
    if not internal_user_id:
        internal_user_id = db.get_or_create_user(user.id).get("id")

    await context.bot.send_chat_action(chat_id=chat.id, action="typing")
    start = time.perf_counter()
    response = await openai_safe.safe_openai_call(
        lambda: assistant.send_message_and_get_response(user.id, user_message),
        timeout=openai_safe.ASSISTANT_RUN_WAIT_TIMEOUT + 5,
        request_type=request_type,
        telegram_id=user.id,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    is_run_timeout = response is openai_safe.RUN_TIMEOUT_SENTINEL
    success = 1 if (response is not None and not is_run_timeout) else 0
    db.log_user_request(
        internal_user_id,
        request_type,
        request_text=request_text,
        success=success,
        response_time_ms=elapsed_ms if response and not is_run_timeout else None,
    )

    if response is None:
        await _send_service_unavailable(update, context, chat.id)
        return
    if is_run_timeout:
        await _send_run_timeout(update, context, chat.id)
        return
    response = format_assistant_response_for_telegram(response)
    await update.message.reply_text(response, parse_mode="HTML")
    await _send_cta(update, context, chat.id)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню (/menu)."""
    await update.message.reply_text(
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(),
    )


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий кнопок главного меню."""
    text = update.message.text if update.message else None
    if not text or text not in MENU_TEXT_TO_COMMAND:
        return
    cmd = MENU_TEXT_TO_COMMAND[text]
    if cmd == "forecast_today":
        await today_forecast_command(update, context)
    elif cmd == "forecast_tomorrow":
        await tomorrow_forecast_command(update, context)
    elif cmd == "check_action":
        await check_action_start(update, context)
    elif cmd == "favorable":
        await favorable_command(update, context)
    elif cmd == "topics":
        await topics_command(update, context)
    elif cmd == "my_data":
        await my_data_command(update, context)


def _build_day_forecast_prompt(user_data: dict, for_today: bool) -> str:
    """Собрать текст запроса к ассистенту (дата «Сегодня» добавляется в assistant.py)."""
    data_str = format_user_data_for_prompt(user_data)
    if for_today:
        instruction = (
            "Сделай персонализированный астрологический прогноз на сегодня для этого человека.\n"
            "Ответ должен быть кратким и практичным."
        )
    else:
        instruction = (
            "Сделай персонализированный астрологический прогноз на завтрашний день для этого человека.\n"
            "Ответ должен быть кратким и практичным."
        )
    return f"Данные пользователя:\n{data_str}\n\n{instruction}"


async def today_forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прогноз на сегодня (кнопка «🔮 Сегодня»)."""
    user = update.effective_user
    if not user:
        return
    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return
    user_data = db.get_user(user.id)
    message = _build_day_forecast_prompt(user_data, for_today=True)
    await ask_assistant_and_reply(update, context, message, request_type="today")


async def tomorrow_forecast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прогноз на завтра (кнопка «🔮 Завтра» и /tomorrow)."""
    user = update.effective_user
    if not user:
        return
    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return
    user_data = db.get_user(user.id)
    message = _build_day_forecast_prompt(user_data, for_today=False)
    await ask_assistant_and_reply(update, context, message, request_type="tomorrow")


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
    internal_user_id = user_data.get("id") or db.get_or_create_user(user.id).get("id")
    data_str = format_user_data_for_prompt(user_data)
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        f"Дай персонализированный прогноз по теме «{topic_label}» для этого человека."
    )

    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
    start = time.perf_counter()
    response = await openai_safe.safe_openai_call(
        lambda: assistant.send_message_and_get_response(user.id, message),
        timeout=openai_safe.ASSISTANT_RUN_WAIT_TIMEOUT + 5,
        request_type="topic",
        telegram_id=user.id,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    is_run_timeout = response is openai_safe.RUN_TIMEOUT_SENTINEL
    success = 1 if (response is not None and not is_run_timeout) else 0
    db.log_user_request(
        internal_user_id,
        "topic",
        request_text=topic_label,
        success=success,
        response_time_ms=elapsed_ms if response and not is_run_timeout else None,
    )

    if response is None:
        await query.edit_message_text(openai_safe.MSG_SERVICE_UNAVAILABLE)
        await _send_service_unavailable(update, context, query.message.chat_id)
        return
    if is_run_timeout:
        await query.edit_message_text(
            openai_safe.MSG_RUN_TIMEOUT,
            reply_markup=get_main_menu_keyboard(),
        )
        return
    response = format_assistant_response_for_telegram(response)
    await query.edit_message_text(response, parse_mode="HTML")
    await _send_cta(update, context, query.message.chat_id)


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
    await ask_assistant_and_reply(update, context, message, request_type="favorable")


async def check_action_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запуск сценария «Проверить действие»: запрос текста от пользователя."""
    user = update.effective_user
    if not user:
        return
    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return
    context.user_data["awaiting_action_check"] = True
    await update.message.reply_text("Какое действие вы хотите проверить?")


async def _send_action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить «Выбери команду из меню» с клавиатурой."""
    chat = update.effective_chat
    if chat:
        await context.bot.send_message(
            chat_id=chat.id,
            text="Выбери команду из меню:",
            reply_markup=get_main_menu_keyboard(),
        )


async def check_action_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода действия для проверки (после check_action_start или уточнение)."""
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    # Ветка уточнения: по флагу или по резервному ключу (на случай потери флага)
    is_clarification = context.user_data.get("awaiting_action_details") or context.user_data.get("pending_action_context") is not None
    if is_clarification:
        context.user_data["awaiting_action_details"] = False
        action_context = (
            context.user_data.pop("action_context", "")
            or context.user_data.pop("pending_action_context", "")
        )
        clarification = update.message.text.strip()
        # очищаем резервный ключ на случай входа по нему
        context.user_data.pop("pending_action_context", None)
        action_clean = f"{action_context} {clarification}".strip() if action_context else clarification
        if not action_clean:
            await update.message.reply_text("Напиши, какое действие хотите проверить.")
            context.user_data["awaiting_action_check"] = True
            return
        try:
            user_data = db.get_user(user.id)
            data_str = format_user_data_for_prompt(user_data) if user_data else ""
            message = (
                f"Данные пользователя:\n{data_str}\n\n"
                f"Пользователь хочет проверить действие: «{action_clean}».\n"
                "Дай краткий ответ: подходит ли день/момент для этого действия."
            )
            await ask_assistant_and_reply(
                update, context, message, request_type="check_action", request_text=action_clean
            )
        except Exception as e:
            logger.exception("Ошибка при ответе после уточнения действия: %s", e)
            await _send_service_unavailable(update, context)
        await _send_action_menu(update, context)
        return

    # Не в сценарии «Проверить действие» — чтобы не оставлять пользователя без ответа, показываем меню
    if not context.user_data.get("awaiting_action_check"):
        await update.message.reply_text(
            "Выбери команду из меню:",
            reply_markup=get_main_menu_keyboard(),
        )
        return
    context.user_data["awaiting_action_check"] = False

    action_text = update.message.text.strip()
    if not action_text:
        await update.message.reply_text("Напиши, какое действие хотите проверить.")
        context.user_data["awaiting_action_check"] = True
        return

    # Шаг 1: эвристика + дешёвая LLM (validate_action)
    result = await openai_safe.safe_openai_call(
        lambda: action_validation.validate_action(action_text),
        timeout=openai_safe.VALIDATION_TIMEOUT,
        request_type="check_action",
        telegram_id=user.id,
    )
    if result is None:
        await _send_service_unavailable(update, context)
        return

    if result.get("heuristic_fail"):
        await update.message.reply_text(result["question_to_user"])
        context.user_data["awaiting_action_check"] = True  # остаёмся в сценарии, можно ввести действие снова
        return

    if result.get("parse_error"):
        await update.message.reply_text(result["question_to_user"])
        context.user_data["awaiting_action_check"] = True
        return

    if not result.get("is_action"):
        reply = result["question_to_user"]
        if reply:
            reply += "\n\n" + EXAMPLES_ACTION
        await update.message.reply_text(reply or EXAMPLES_ACTION)
        context.user_data["awaiting_action_check"] = True  # остаёмся в сценарии для повторной попытки
        return

    if result.get("needs_details"):
        action_clean_val = result["action_clean"]
        context.user_data["action_context"] = action_clean_val
        context.user_data["pending_action_context"] = action_clean_val  # резерв, если флаг потеряется
        context.user_data["awaiting_action_details"] = True
        await update.message.reply_text(result["question_to_user"] or "Уточните, пожалуйста.")
        return

    # is_action=True, needs_details=False — вызываем дорогого ассистента
    action_clean = result.get("action_clean") or action_text
    user_data = db.get_user(user.id)
    data_str = format_user_data_for_prompt(user_data) if user_data else ""
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        f"Пользователь хочет проверить действие: «{action_clean}».\n"
        "Дай краткий ответ: подходит ли день/момент для этого действия."
    )
    await ask_assistant_and_reply(
        update, context, message, request_type="check_action", request_text=action_clean
    )
    await _send_action_menu(update, context)


async def my_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущие данные рождения и кнопку «Изменить данные»."""
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await update.message.reply_text(
            "Данные рождения не заполнены. Отправь /start или нажми «Изменить данные» для ввода.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    u = db.get_user(user.id)
    text = (
        "Твои данные рождения:\n"
        f"Дата: {u.get('birth_date', '—')}\n"
        f"Время: {u.get('birth_time', '—')}\n"
        f"Место: {u.get('birth_place', '—')}\n\n"
        "Чтобы изменить, нажми кнопку ниже или отправь /setdata."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Изменить данные", callback_data="action_setdata")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


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


async def cta_full_access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заглушка по нажатию «Полный доступ»: сообщение о подписке и показ меню."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Скоро: подписка 149 ₽/мес + безлимит",
        reply_markup=get_main_menu_keyboard(),
    )
