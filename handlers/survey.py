"""Опросник onboarding_v1: 8 вопросов, бонус PRO на 3 дня."""

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import db
from handlers.common import MENU_TEXT_TO_COMMAND, conversation_reset, get_main_menu_keyboard

logger = logging.getLogger(__name__)

SURVEY_CODE = "onboarding_v1"
STATE_SURVEY_CONFIRM = 50
STATE_SURVEY_QUESTION = 51

CALLBACK_SURVEY_YES = "survey_yes"
CALLBACK_SURVEY_CANCEL = "survey_cancel"
CALLBACK_SURVEY_CHOICE_PREFIX = "survey_c_"
CALLBACK_SURVEY_SCALE_PREFIX = "survey_s_"


async def survey_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запуск опроса: /survey или кнопка меню. Проверка «уже проходил», иначе — подтверждение."""
    user = update.effective_user
    if not user:
        return ConversationHandler.END
    conversation_reset(update, context, "survey")
    telegram_id = user.id
    db.get_or_create_user(telegram_id)
    row = db.get_user(telegram_id)
    internal_user_id = row["id"]
    survey = db.get_active_survey_by_code(SURVEY_CODE)
    if not survey:
        await update.message.reply_text("Опрос временно недоступен.")
        return ConversationHandler.END
    survey_id = survey["id"]
    if db.has_completed_survey(internal_user_id, survey_id):
        await update.message.reply_text(
            "Вы уже проходили опрос. Спасибо! ❤️",
            reply_markup=get_main_menu_keyboard(telegram_id),
        )
        return ConversationHandler.END
    context.user_data["survey_internal_user_id"] = internal_user_id
    context.user_data["survey_telegram_id"] = telegram_id
    context.user_data["survey_id"] = survey_id
    context.user_data["survey_code"] = SURVEY_CODE
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data=CALLBACK_SURVEY_YES)],
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_SURVEY_CANCEL)],
    ])
    await update.message.reply_text(
        "Опрос займёт 1–2 минуты. После — бонус PRO на 3 дня. Начнём? ✅",
        reply_markup=keyboard,
    )
    logger.info("survey_start user_id=%s telegram_id=%s survey_code=%s", internal_user_id, telegram_id, SURVEY_CODE)
    return STATE_SURVEY_CONFIRM


async def survey_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка «Да» / «Отмена» на подтверждении опроса."""
    query = update.callback_query
    if not query:
        return STATE_SURVEY_CONFIRM
    await query.answer()
    if query.data == CALLBACK_SURVEY_CANCEL:
        await query.edit_message_text("Опрос отменён.")
        return ConversationHandler.END
    if query.data != CALLBACK_SURVEY_YES:
        return STATE_SURVEY_CONFIRM
    internal_user_id = context.user_data.get("survey_internal_user_id")
    survey_id = context.user_data.get("survey_id")
    if not internal_user_id or not survey_id:
        await query.edit_message_text("Сессия сброшена. Запустите опрос снова.")
        return ConversationHandler.END
    run_id = db.create_survey_run(internal_user_id, survey_id)
    survey = db.get_active_survey_by_code(SURVEY_CODE)
    questions = survey["questions"]
    context.user_data["survey_run_id"] = run_id
    context.user_data["survey_questions"] = questions
    context.user_data["survey_index"] = 0
    text = f"Вопрос 1/{len(questions)}.\n\n" + _format_question(questions[0])
    keyboard = _keyboard_for_question(questions[0], run_id, 0)
    if keyboard:
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await query.edit_message_text(text)
    return STATE_SURVEY_QUESTION


def _format_question(q: dict) -> str:
    """Текст вопроса для отправки пользователю."""
    return q.get("text", "")


def _keyboard_for_question(q: dict, run_id: int, q_index: int) -> InlineKeyboardMarkup | None:
    """Inline-клавиатура для choice/scale; для text возвращает None."""
    qtype = q.get("type")
    if qtype == "choice":
        choices = q.get("choices") or []
        buttons = [
            [InlineKeyboardButton(c, callback_data=f"{CALLBACK_SURVEY_CHOICE_PREFIX}{run_id}_{q_index}_{i}")]
            for i, c in enumerate(choices)
        ]
        return InlineKeyboardMarkup(buttons)
    if qtype == "scale":
        min_v = int(q.get("min", 1))
        max_v = int(q.get("max", 10))
        mid = (min_v + max_v) // 2
        row1 = [
            InlineKeyboardButton(str(i), callback_data=f"{CALLBACK_SURVEY_SCALE_PREFIX}{run_id}_{q_index}_{i}")
            for i in range(min_v, mid + 1)
        ]
        row2 = [
            InlineKeyboardButton(str(i), callback_data=f"{CALLBACK_SURVEY_SCALE_PREFIX}{run_id}_{q_index}_{i}")
            for i in range(mid + 1, max_v + 1)
        ]
        rows = [row1] + ([row2] if row2 else [])
        return InlineKeyboardMarkup(rows)
    return None


async def _send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправить следующий вопрос или завершить опрос. Возвращает следующее состояние."""
    run_id = context.user_data.get("survey_run_id")
    questions = context.user_data.get("survey_questions")
    index = context.user_data.get("survey_index", 0)
    internal_user_id = context.user_data.get("survey_internal_user_id")
    telegram_id = context.user_data.get("survey_telegram_id")
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id or run_id is None or not questions or internal_user_id is None or telegram_id is None:
        return ConversationHandler.END
    if index >= len(questions):
        pro_until_str = db.complete_run_and_grant_bonus(run_id, internal_user_id, telegram_id, days=3)
        logger.info("survey_completed user_id=%s survey_code=%s bonus_until=%s", internal_user_id, SURVEY_CODE, pro_until_str)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Спасибо! ✅ Бонус: PRO активирован до {pro_until_str}.",
            reply_markup=get_main_menu_keyboard(telegram_id),
        )
        for key in list(context.user_data.keys()):
            if key.startswith("survey_"):
                del context.user_data[key]
        return ConversationHandler.END
    q = questions[index]
    text = f"Вопрос {index + 1}/{len(questions)}.\n\n" + _format_question(q)
    keyboard = _keyboard_for_question(q, run_id, index)
    if keyboard:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text)
    return STATE_SURVEY_QUESTION


async def survey_question_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ответ текстом (type=text)."""
    msg_text = (update.message.text or "").strip()
    if msg_text in MENU_TEXT_TO_COMMAND:
        await update.message.reply_text("Сейчас идёт опрос. Используйте кнопки выше или /cancel для отмены.")
        return STATE_SURVEY_QUESTION
    questions = context.user_data.get("survey_questions")
    index = context.user_data.get("survey_index", 0)
    run_id = context.user_data.get("survey_run_id")
    if run_id is None or not questions or index >= len(questions):
        return ConversationHandler.END
    q = questions[index]
    if q.get("type") != "text":
        await update.message.reply_text("Выберите вариант кнопкой выше.")
        return STATE_SURVEY_QUESTION
    text = msg_text or "(пусто)"
    db.save_survey_answer(run_id, q["key"], answer_text=text)
    context.user_data["survey_index"] = index + 1
    return await _send_next_question(update, context)


async def survey_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ответ по кнопке (choice/scale)."""
    query = update.callback_query
    if not query:
        return STATE_SURVEY_QUESTION
    await query.answer()
    data = query.data or ""
    questions = context.user_data.get("survey_questions")
    index = context.user_data.get("survey_index", 0)
    run_id = context.user_data.get("survey_run_id")
    if run_id is None or not questions or index >= len(questions):
        return ConversationHandler.END
    q = questions[index]
    if data.startswith(CALLBACK_SURVEY_CHOICE_PREFIX):
        parts = data[len(CALLBACK_SURVEY_CHOICE_PREFIX):].split("_")
        if len(parts) >= 3 and int(parts[0]) == run_id and int(parts[1]) == index:
            choice_idx = int(parts[2])
            choices = q.get("choices") or []
            if 0 <= choice_idx < len(choices):
                db.save_survey_answer(run_id, q["key"], answer_choice=choices[choice_idx])
    elif data.startswith(CALLBACK_SURVEY_SCALE_PREFIX):
        parts = data[len(CALLBACK_SURVEY_SCALE_PREFIX):].split("_")
        if len(parts) >= 3 and int(parts[0]) == run_id and int(parts[1]) == index:
            try:
                num = float(parts[2])
                db.save_survey_answer(run_id, q["key"], answer_number=num)
            except ValueError:
                pass
    else:
        return STATE_SURVEY_QUESTION
    context.user_data["survey_index"] = index + 1
    return await _send_next_question(update, context)


async def survey_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена опроса (команда /cancel или выход)."""
    run_id = context.user_data.get("survey_run_id")
    if run_id is not None:
        db.abandon_survey_run(run_id)
    telegram_id = update.effective_user.id if update.effective_user else None
    for key in list(context.user_data.keys()):
        if key.startswith("survey_"):
            del context.user_data[key]
    await update.message.reply_text(
        "Опрос отменён.",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )
    return ConversationHandler.END


async def survey_fallback_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback: нажатие кнопки меню во время опроса — сброс и выход из диалога."""
    conversation_reset(update, context, "survey_fallback_menu_button")
    run_id = context.user_data.get("survey_run_id")
    if run_id is not None:
        db.abandon_survey_run(run_id)
    telegram_id = update.effective_user.id if update.effective_user else None
    for key in list(context.user_data.keys()):
        if key.startswith("survey_"):
            del context.user_data[key]
    await update.message.reply_text(
        "Выбери команду из меню:",
        reply_markup=get_main_menu_keyboard(telegram_id),
    )
    return ConversationHandler.END
