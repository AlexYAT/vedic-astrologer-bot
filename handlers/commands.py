"""Команды: Сегодня/Завтра, Проверить действие, Удачный день, По теме, Мои данные; /menu, /setdata."""

import logging
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import action_validation
import assistant
import config
import db
import openai_safe
from handlers.common import (
    CTA_TEXT,
    CHECK_ACTION_AGAIN_CALLBACK,
    CHECK_ACTION_MENU_CALLBACK,
    conversation_reset,
    format_assistant_response_for_telegram,
    get_check_action_followup_keyboard,
    get_cta_keyboard,
    get_main_menu_keyboard,
    get_topics_keyboard,
    get_topic_label,
    MENU_TEXT_TO_COMMAND,
)
from handlers.start import STATE_BIRTH_DATE

EXAMPLES_ACTION = "Пример: подписать договор, подать заявление, поговорить с руководителем."

CHECK_ACTION_PROMPT = (
    "Опишите действие одной фразой. "
    "Пример: «полететь в отпуск на Чёрное море», «подписать договор»."
)
CHECK_ACTION_TOO_GENERAL = (
    "Похоже, действие пока слишком общее. Напишите одной фразой в формате: «сделать X (где/с кем/когда)». "
    "Примеры: полететь в отпуск на Чёрное море, подписать договор с застройщиком, поговорить с руководителем о повышении."
)

logger = logging.getLogger(__name__)

MSG_NEED_DATA = (
    "Для получения прогноза необходимо заполнить данные рождения. "
    "Отправь /start или /setdata для ввода."
)


def format_user_data_for_prompt(user: dict) -> str:
    """Формирование строки с данными пользователя для промпта ассистенту."""
    birth_time_unknown = user.get('birth_time_unknown', False)
    if birth_time_unknown:
        time_str = "неизвестно"
    else:
        time_str = user.get('birth_time', 'не указано')
    
    parts = [
        f"Дата рождения: {user.get('birth_date', 'не указана')}",
        f"Время рождения: {time_str}",
        f"Место рождения: {user.get('birth_place', 'не указано')}",
    ]
    
    result = "\n".join(parts)
    
    # Добавляем предупреждение для ассистента, если время неизвестно
    if birth_time_unknown:
        result += "\n\nВремя рождения неизвестно. Делай прогноз по общему натальному фону и транзитам, не опирайся на лагну и точные дома."
    
    return result


def _append_mode_footer(
    text: str, telegram_id: int, debug_info: dict | None = None
) -> str:
    """Добавить подпись режима FREE/PRO и при FREE — строку про PRO. Debug-строка только при DEBUG_SHOW_TO_USERS=1 и telegram_id в DEBUG_USERS."""
    mode = assistant.get_user_mode(telegram_id)
    
    # Проверяем, неизвестно ли время рождения
    user_data = db.get_user(telegram_id)
    birth_time_unknown = user_data.get('birth_time_unknown', False) if user_data else False
    
    # Добавляем предупреждение о неизвестном времени перед режимом
    if birth_time_unknown:
        text += "\n\nℹ️ Прогноз без точного времени рождения — точность ниже. Если узнаете время, обновите профиль."
    
    if mode == "PRO":
        out = text + "\n\n💎 Режим: PRO"
    else:
        out = text + "\n\n🆓 Режим: FREE\nВ PRO — больше точности и деталей."
    show_debug = (
        telegram_id is not None
        and config.get_debug_show_to_users()
        and telegram_id in config.get_debug_users()
        and debug_info
    )
    if show_debug:
        parts = [
            f"mode={debug_info.get('mode', '?')}",
            f"assistant_id={debug_info.get('assistant_id', '')}",
            f"thread_id={debug_info.get('thread_id', '')}",
            f"run_id={debug_info.get('run_id', '')}",
        ]
        if debug_info.get("key") is not None:
            parts.append(f"key={debug_info.get('key')!r}")
        if debug_info.get("final_action") is not None:
            parts.append(f"final_action={debug_info.get('final_action')!r}")
        out += "\n\ndebug: " + " ".join(parts)
    return out


async def _send_service_unavailable(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None
) -> None:
    """Отправить сообщение о недоступности сервиса и показать главное меню."""
    target = chat_id or (update.effective_chat.id if update.effective_chat else None)
    if target is None:
        return
    telegram_id = update.effective_user.id if update.effective_user else None
    await context.bot.send_message(
        chat_id=target,
        text=openai_safe.MSG_SERVICE_UNAVAILABLE,
        reply_markup=get_main_menu_keyboard(telegram_id),
    )


async def _send_run_timeout(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None
) -> None:
    """Ответ готовится дольше обычного: сообщение и меню (новый run не создаём)."""
    target = chat_id or (update.effective_chat.id if update.effective_chat else None)
    if target is None:
        return
    telegram_id = update.effective_user.id if update.effective_user else None
    await context.bot.send_message(
        chat_id=target,
        text=openai_safe.MSG_RUN_TIMEOUT,
        reply_markup=get_main_menu_keyboard(telegram_id),
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
    extra_debug: dict | None = None,
) -> None:
    """
    Отправить запрос ассистенту, показать ответ. CTA «Полный доступ» — только в режиме FREE.
    При timeout или ошибке API — сообщение о недоступности и меню.
    extra_debug: доп. поля для debug-строки (например final_action для check_action).
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
    mode, assistant_id_suffix = assistant.get_user_mode_and_suffix(user.id)
    start = time.perf_counter()
    result = await openai_safe.safe_openai_call(
        lambda: assistant.send_message_and_get_response(
            user.id, user_message, request_type=request_type
        ),
        timeout=openai_safe.ASSISTANT_RUN_WAIT_TIMEOUT + 5,
        request_type=request_type,
        telegram_id=user.id,
        mode=mode,
        assistant_id_suffix=assistant_id_suffix,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    if isinstance(result, tuple):
        response, debug_info = result[0], result[1]
    else:
        response, debug_info = result, None
    if extra_debug and debug_info is not None:
        debug_info = {**debug_info, **extra_debug}
    elif extra_debug:
        debug_info = extra_debug
    is_run_timeout = response is openai_safe.RUN_TIMEOUT_SENTINEL
    success = 1 if (response is not None and not is_run_timeout) else 0
    db.log_user_request(
        internal_user_id,
        request_type,
        request_text=request_text,
        success=success,
        response_time_ms=elapsed_ms if response and not is_run_timeout else None,
        mode=mode,
    )

    if response is None:
        await _send_service_unavailable(update, context, chat.id)
        return
    if is_run_timeout:
        await _send_run_timeout(update, context, chat.id)
        return
    response = format_assistant_response_for_telegram(response)
    response = _append_mode_footer(response, user.id, debug_info=debug_info)
    await update.message.reply_text(response, parse_mode="HTML")
    if mode == "FREE":
        await _send_cta(update, context, chat.id)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню (/menu)."""
    user = update.effective_user
    if not user:
        return
    conversation_reset(update, context, "menu")
    telegram_id = user.id
    await update.message.reply_text(
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )


MODE_SWITCH_HINT_PRO = (
    "💎 Попробуйте PRO на «Проверить действие» — там разница сильнее всего."
)


async def mode_switch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переключение режима FREE <-> PRO: лог, сохранение в БД, подсказка при включении PRO, обновлённое меню."""
    user = update.effective_user
    if not user:
        return
    conversation_reset(update, context, "mode_switch")
    telegram_id = user.id
    db.get_or_create_user(telegram_id)
    old_mode = db.get_user_mode(telegram_id)
    new_mode = "pro" if old_mode == "free" else "free"
    db.set_user_mode(telegram_id, new_mode)
    logger.info(
        "mode_switch telegram_id=%s old_mode=%s new_mode=%s",
        telegram_id,
        old_mode,
        new_mode,
    )
    row = db.get_user(telegram_id)
    internal_user_id = row.get("id")
    if internal_user_id is not None:
        db.log_user_request(
            internal_user_id,
            "mode_switch",
            request_text=f"{old_mode}->{new_mode}",
            success=1,
            response_time_ms=None,
            mode=new_mode,
        )
    label = "✅ Включен режим PRO" if new_mode == "pro" else "✅ Включен режим FREE"
    await update.message.reply_text(label)
    if new_mode == "pro":
        await update.message.reply_text(MODE_SWITCH_HINT_PRO)
    await update.message.reply_text(
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий кнопок главного меню. Сброс предыдущего состояния перед диспетчеризацией."""
    text = update.message.text if update.message else None
    if not text or text not in MENU_TEXT_TO_COMMAND:
        return
    
    conversation_reset(update, context, "menu_button")
    
    cmd = MENU_TEXT_TO_COMMAND[text]
    if cmd == "mode_switch":
        await mode_switch_command(update, context)
        return
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
    # cmd == "survey": сообщение "📝 Опрос (бонус PRO)" обрабатывается survey_conv (entry_point) раньше этого handler'а


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
    mode, assistant_id_suffix = assistant.get_user_mode_and_suffix(user.id)
    start = time.perf_counter()
    result = await openai_safe.safe_openai_call(
        lambda: assistant.send_message_and_get_response(
            user.id, message, request_type="topic"
        ),
        timeout=openai_safe.ASSISTANT_RUN_WAIT_TIMEOUT + 5,
        request_type="topic",
        telegram_id=user.id,
        mode=mode,
        assistant_id_suffix=assistant_id_suffix,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    if isinstance(result, tuple):
        response, debug_info = result[0], result[1]
    else:
        response, debug_info = result, None
    is_run_timeout = response is openai_safe.RUN_TIMEOUT_SENTINEL
    success = 1 if (response is not None and not is_run_timeout) else 0
    db.log_user_request(
        internal_user_id,
        "topic",
        request_text=topic_label,
        success=success,
        response_time_ms=elapsed_ms if response and not is_run_timeout else None,
        mode=mode,
    )

    if response is None:
        await query.edit_message_text(openai_safe.MSG_SERVICE_UNAVAILABLE)
        await _send_service_unavailable(update, context, query.message.chat_id)
        return
    if is_run_timeout:
        await query.edit_message_text(
            openai_safe.MSG_RUN_TIMEOUT,
            reply_markup=get_main_menu_keyboard(user.id),
        )
        return
    response = format_assistant_response_for_telegram(response)
    response = _append_mode_footer(response, user.id, debug_info=debug_info)
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
    """Запуск сценария «Проверить действие»: сброс шага и запрос действия одной фразой."""
    user = update.effective_user
    if not user:
        return
    if not db.user_has_full_data(user.id):
        await update.message.reply_text(MSG_NEED_DATA)
        return
    context.user_data["action_draft"] = ""
    context.user_data["check_action_step"] = 0
    await update.message.reply_text(CHECK_ACTION_PROMPT)


async def _send_check_action_followup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """После ответа по «Проверить действие»: кнопки «Ещё действие», «Меню»."""
    chat = update.effective_chat
    if not chat:
        return
    await context.bot.send_message(
        chat_id=chat.id,
        text="Проверить другое действие или вернуться в меню:",
        reply_markup=get_check_action_followup_keyboard(),
    )


async def _send_action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить «Выбери команду из меню» с клавиатурой."""
    chat = update.effective_chat
    telegram_id = update.effective_user.id if update.effective_user else None
    if chat:
        await context.bot.send_message(
            chat_id=chat.id,
            text="Выбери команду из меню:",
            reply_markup=get_main_menu_keyboard(telegram_id),
        )


async def check_action_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработка ввода в сценарии «Проверить действие».
    user_data: action_draft (накопленный текст), check_action_step (0 или 1).
    Максимум одно уточнение, затем либо итоговое действие в ассистента, либо просьба написать одной фразой.
    """
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    # Не в сценарии «Проверить действие» — показываем меню
    step = context.user_data.get("check_action_step")
    if step not in (0, 1):
        # Поддержка старого флага для плавного перехода
        if not context.user_data.get("awaiting_action_check"):
            telegram_id = update.effective_user.id if update.effective_user else None
            await update.message.reply_text(
                "Выбери команду из меню:",
                reply_markup=get_main_menu_keyboard(telegram_id),
            )
            return
        context.user_data["action_draft"] = ""
        context.user_data["check_action_step"] = 0

    # Накапливаем ввод в action_draft
    new_text = update.message.text.strip()
    draft = (context.user_data.get("action_draft") or "") + (" " + new_text if new_text else "")
    draft = draft.strip()
    context.user_data["action_draft"] = draft

    if not draft:
        await update.message.reply_text(CHECK_ACTION_PROMPT)
        return

    # Валидация (эвристика + LLM)
    result = await openai_safe.safe_openai_call(
        lambda: action_validation.validate_action(draft),
        timeout=openai_safe.VALIDATION_TIMEOUT,
        request_type="check_action",
        telegram_id=user.id,
    )
    if result is None:
        await _send_service_unavailable(update, context)
        return

    if result.get("heuristic_fail"):
        await update.message.reply_text(result["question_to_user"] + "\n\n" + EXAMPLES_ACTION)
        return

    if result.get("parse_error"):
        await update.message.reply_text(result["question_to_user"] + "\n\n" + EXAMPLES_ACTION)
        return

    if not result.get("is_action"):
        reply = result.get("question_to_user") or ""
        if reply:
            reply += "\n\n"
        await update.message.reply_text(reply + EXAMPLES_ACTION)
        return

    # is_action=True
    if result.get("needs_details") and context.user_data.get("check_action_step") == 0:
        context.user_data["check_action_step"] = 1
        await update.message.reply_text(result.get("question_to_user") or "Уточните, пожалуйста.")
        return

    if result.get("needs_details") and context.user_data.get("check_action_step") == 1:
        context.user_data["action_draft"] = ""
        context.user_data["check_action_step"] = 0
        await update.message.reply_text(CHECK_ACTION_TOO_GENERAL)
        return

    # is_action=True, needs_details=False — отправляем в ассистента
    action_clean = (result.get("action_clean") or "").strip() or draft
    final_action = action_clean
    mode, _ = assistant.get_user_mode_and_suffix(user.id)
    logger.info(
        "request_type=check_action telegram_id=%s mode=%s final_action=%s",
        user.id,
        mode,
        final_action,
    )

    user_data = db.get_user(user.id)
    data_str = format_user_data_for_prompt(user_data) if user_data else ""
    message = (
        f"Данные пользователя:\n{data_str}\n\n"
        f"Пользователь хочет проверить действие:\n«{final_action}».\n\n"
        "Ответь строго про это действие.\n\n"
        "1. Подходит ли текущий день для выполнения именно этого действия?\n"
        "2. Какие риски связаны именно с этим действием?\n"
        "3. Есть ли смысл перенести его?\n\n"
        "Не давай общий прогноз дня.\n"
        "Не уходи в общие темы.\n"
        f"Ответ должен быть сфокусирован только на действии «{final_action}».\n\n"
        "Ответ строго по формату текущего режима (FREE/PRO)."
    )

    await ask_assistant_and_reply(
        update,
        context,
        message,
        request_type="check_action",
        request_text=final_action,
        extra_debug={"final_action": final_action},
    )
    context.user_data.pop("action_draft", None)
    context.user_data.pop("check_action_step", None)
    await _send_check_action_followup(update, context)


async def check_action_again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Ещё действие»: сброс и возврат в состояние ввода."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    context.user_data["action_draft"] = ""
    context.user_data["check_action_step"] = 0
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=CHECK_ACTION_PROMPT,
    )


async def check_action_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Меню» после проверки действия: сброс состояния и главное меню."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    context.user_data.pop("action_draft", None)
    context.user_data.pop("check_action_step", None)
    telegram_id = query.from_user.id if query.from_user else None
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )


async def my_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущие данные рождения и кнопку «Изменить данные»."""
    user = update.effective_user
    if not user:
        return

    if not db.user_has_full_data(user.id):
        await update.message.reply_text(
            "Данные рождения не заполнены. Отправь /start или нажми «Изменить данные» для ввода.",
            reply_markup=get_main_menu_keyboard(user.id),
        )
        return

    u = db.get_user(user.id)
    birth_time_unknown = u.get('birth_time_unknown', False)
    time_display = "неизвестно" if birth_time_unknown else u.get('birth_time', '—')
    
    text = (
        "📌 Принято:\n"
        f"Дата: {u.get('birth_date', '—')}\n"
        f"Время: {time_display}\n"
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
    telegram_id = query.from_user.id if query.from_user else None
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Скоро: подписка 149 ₽/мес + безлимит",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )
