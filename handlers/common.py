"""Общие функции: клавиатуры, валидация."""

import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

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


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с основными командами."""
    keyboard = [
        [KeyboardButton("/tomorrow"), KeyboardButton("/topics")],
        [KeyboardButton("/favorable"), KeyboardButton("/contact")],
        [KeyboardButton("/setdata")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


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
