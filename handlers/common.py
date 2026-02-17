"""Общие функции: клавиатуры, валидация, форматирование ответов."""

import html
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

import config
import db

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from telegram import User

# Плейсхолдеры для конвертации Markdown → HTML (не содержат <>&)
_PLACEHOLDER_BOLD_OPEN = "\uE000"
_PLACEHOLDER_BOLD_CLOSE = "\uE001"

# Кнопки главного меню: (подпись, имя команды)
MAIN_MENU_BUTTONS = [
    ("🔮 Сегодня", "forecast_today"),
    ("🔮 Завтра", "forecast_tomorrow"),
    ("❓ Проверить действие", "check_action"),
    ("📅 Удачный день", "favorable"),
    ("🎯 По теме", "topics"),
    ("⚙️ Мои данные", "my_data"),
    ("📝 Опрос (бонус PRO)", "survey"),
]
MODE_SWITCH_LABEL_FREE = "🔁 Режим: FREE"
MODE_SWITCH_LABEL_PRO = "🔁 Режим: PRO"
MENU_TEXT_TO_COMMAND = {label: cmd for label, cmd in MAIN_MENU_BUTTONS}
MENU_TEXT_TO_COMMAND[MODE_SWITCH_LABEL_FREE] = "mode_switch"
MENU_TEXT_TO_COMMAND[MODE_SWITCH_LABEL_PRO] = "mode_switch"

# Regex для текста любой кнопки главного меню (для fallback в ConversationHandler)
MENU_BUTTONS_REGEX = (
    r"^(🔮 Сегодня|🔮 Завтра|❓ Проверить действие|📅 Удачный день|🎯 По теме|"
    r"⚙️ Мои данные|📝 Опрос \(бонус PRO\)|🔁 Режим: FREE|🔁 Режим: PRO)$"
)


def conversation_reset(update, context, reason: str) -> None:
    """
    Сброс состояния диалога: очистка context.user_data и лог.
    Вызывать при входе в /start, /menu, кнопку «Опрос», «Режим» и при нажатии любой кнопки меню.
    """
    user_id = None
    if update and getattr(update, "effective_user", None) and update.effective_user:
        user_id = update.effective_user.id
    context.user_data.clear()
    logger.info("conversation_reset user_id=%s reason=%s", user_id, reason)


# CTA после каждого ответа ассистента
CTA_TEXT = "Хотите больше точности? Доступно в полной версии"
CTA_FULL_ACCESS_CALLBACK = "cta_full_access"

def get_user_display_name(user: "User | None") -> str:
    """
    Имя пользователя для приветствия: first_name, при наличии — first_name + last_name.
    Если определить нельзя — «друг».
    """
    if not user:
        return "друг"
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if user.username:
        return f"@{user.username}"
    return "друг"


# Тематики для /topics
TOPICS = [
    ("career", "Карьера"),
    ("relationships", "Отношения"),
    ("health", "Здоровье"),
    ("finance", "Финансы"),
    ("spirituality", "Духовность"),
]


def validate_birth_date(text: str) -> bool:
    """Проверка формата даты рождения ДД.ММ.ГГГГ."""
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text.strip())
    if not match:
        return False
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        dt = datetime(year, month, day)
        return 1900 <= year <= 2030 and dt.year == year and dt.month == month and dt.day == day
    except ValueError:
        return False


def is_birth_time_unknown(text: str) -> bool:
    """Проверка, указал ли пользователь, что время рождения неизвестно."""
    text_lower = text.strip().lower()
    unknown_values = ["не знаю", "неизвестно", "нет", "примерно", "-", "?", ""]
    return text_lower in unknown_values


def validate_birth_time(text: str) -> bool:
    """Проверка формата времени рождения ЧЧ:ММ."""
    match = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
    if not match:
        return False
    hour, minute = int(match.group(1)), int(match.group(2))
    return 0 <= hour <= 23 and 0 <= minute <= 59


def validate_email(text: str) -> bool:
    """Базовая проверка формата email."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, text.strip())) if text.strip() else True


def can_see_mode_switch(telegram_id: Optional[int]) -> bool:
    """Кнопка переключения режима видна по MODE_SWITCH_VISIBILITY: off — никому, public — всем, testers — только из MODE_SWITCH_USERS."""
    visibility = config.get_mode_switch_visibility()
    if visibility == "off":
        return False
    if visibility == "public":
        return True
    if visibility == "testers":
        return telegram_id is not None and telegram_id in config.get_mode_switch_users()
    return False


def get_mode_switch_button_label(telegram_id: Optional[int]) -> str:
    """Текст кнопки режима по текущему mode в БД."""
    if telegram_id is None:
        return MODE_SWITCH_LABEL_FREE
    return MODE_SWITCH_LABEL_PRO if db.get_user_mode(telegram_id) == "pro" else MODE_SWITCH_LABEL_FREE


def get_main_menu_keyboard(telegram_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    """
    Клавиатура главного меню (2+2+2), кнопка опроса, при telegram_id и can_see_mode_switch — кнопка «Режим FREE/PRO».
    Кнопка режима размещается в одной строке с кнопкой опроса для экономии места.
    """
    labels = [label for label, _ in MAIN_MENU_BUTTONS]
    keyboard = [
        [KeyboardButton(labels[0]), KeyboardButton(labels[1])],
        [KeyboardButton(labels[2]), KeyboardButton(labels[3])],
        [KeyboardButton(labels[4]), KeyboardButton(labels[5])],
    ]
    
    # Последняя строка: кнопка опроса, при необходимости — вместе с кнопкой режима
    if telegram_id is not None and can_see_mode_switch(telegram_id):
        button_label = get_mode_switch_button_label(telegram_id)
        keyboard.append([KeyboardButton(labels[6]), KeyboardButton(button_label)])
    else:
        keyboard.append([KeyboardButton(labels[6])])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cta_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопка CTA «Полный доступ» после ответа ассистента."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 Полный доступ", callback_data=CTA_FULL_ACCESS_CALLBACK)],
    ])


# Callback для сценария «Проверить действие»
CHECK_ACTION_AGAIN_CALLBACK = "check_action_again"
CHECK_ACTION_MENU_CALLBACK = "check_action_menu"


def get_check_action_followup_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопки после ответа по «Проверить действие»: Ещё действие, Меню."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔁 Ещё действие", callback_data=CHECK_ACTION_AGAIN_CALLBACK),
            InlineKeyboardButton("🏠 Меню", callback_data=CHECK_ACTION_MENU_CALLBACK),
        ],
    ])


def get_topics_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура с темами для прогноза."""
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"topic_{key}")]
        for key, label in TOPICS
    ]
    return InlineKeyboardMarkup(buttons)


def get_topic_label(callback_data: str) -> str | None:
    """Получить название темы по callback_data."""
    prefix = "topic_"
    if callback_data.startswith(prefix):
        key = callback_data[len(prefix):]
        for k, label in TOPICS:
            if k == key:
                return label
    return None


def format_assistant_response_for_telegram(text: str) -> str:
    """
    Нормализует заголовки и переводит ответ ассистента в HTML для Telegram.
    - Строки ### Заголовок и ## Заголовок → жирный заголовок (как **Заголовок:**).
    - **жирный текст** → <b>жирный текст</b>.
    - Экранирует & < > для parse_mode=HTML.
    """
    if not text or not text.strip():
        return text

    # 1) Нормализуем Markdown-заголовки: ### и ## в начале строки → **Заголовок:**
    def normalize_header(match: re.Match) -> str:
        title = match.group(1).strip()
        if title and not title.endswith(":"):
            title = title + ":"
        return "**" + title + "**"

    text = re.sub(r"^#{2,3}\s*(.+)$", normalize_header, text, flags=re.MULTILINE)

    # 2) Заменяем **...** на плейсхолдеры (чтобы после escape не трогать теги)
    parts = []
    pos = 0
    while True:
        start = text.find("**", pos)
        if start == -1:
            parts.append(("text", text[pos:]))
            break
        parts.append(("text", text[pos:start]))
        end = text.find("**", start + 2)
        if end == -1:
            parts.append(("text", text[start:]))
            break
        parts.append(("bold", text[start + 2 : end]))
        pos = end + 2

    # 3) Собираем строку: обычный текст экранируем, bold оборачиваем в плейсхолдеры
    result_parts = []
    for kind, content in parts:
        if kind == "text":
            result_parts.append(html.escape(content))
        else:
            result_parts.append(
                _PLACEHOLDER_BOLD_OPEN + html.escape(content) + _PLACEHOLDER_BOLD_CLOSE
            )

    out = "".join(result_parts)
    out = out.replace(_PLACEHOLDER_BOLD_OPEN, "<b>").replace(_PLACEHOLDER_BOLD_CLOSE, "</b>")
    return out
