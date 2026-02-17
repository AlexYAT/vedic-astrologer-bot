"""Загрузка переменных окружения из .env файла."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загрузка .env из корня проекта
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)


def get_telegram_token() -> str:
    """Получить токен Telegram-бота."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в переменных окружения или .env")
    return token


def get_openai_api_key() -> str:
    """Получить API-ключ OpenAI."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY не задан в переменных окружения или .env")
    return key


def get_assistant_id() -> str:
    """Получить ID ассистента OpenAI (fallback: ASSISTANT_ID_FREE или ASSISTANT_ID)."""
    return get_assistant_id_free()


def get_assistant_id_free() -> str:
    """ID ассистента для режима FREE."""
    aid = os.getenv("ASSISTANT_ID_FREE") or os.getenv("ASSISTANT_ID")
    if not aid:
        raise ValueError(
            "ASSISTANT_ID_FREE или ASSISTANT_ID не задан в переменных окружения или .env"
        )
    return aid


def get_assistant_id_pro() -> str:
    """ID ассистента для режима PRO."""
    aid = os.getenv("ASSISTANT_ID_PRO")
    if not aid:
        raise ValueError("ASSISTANT_ID_PRO не задан в переменных окружения или .env")
    return aid


def get_debug_mode() -> bool:
    """Включён ли режим отладки (DEBUG_MODE=1): детальные INFO-логи. По умолчанию 0. Не влияет на показ debug пользователю."""
    raw = os.getenv("DEBUG_MODE", "0").strip()
    return raw in ("1", "true", "yes", "on")


def get_debug_show_to_users() -> bool:
    """Показывать ли debug-строку в ответе пользователям из DEBUG_USERS. По умолчанию 0."""
    raw = os.getenv("DEBUG_SHOW_TO_USERS", "0").strip()
    return raw in ("1", "true", "yes", "on")


def get_debug_users() -> frozenset[int]:
    """Telegram ID пользователей, которым можно показывать debug в ответе (при DEBUG_SHOW_TO_USERS=1)."""
    raw = os.getenv("DEBUG_USERS", "").strip()
    if not raw:
        return frozenset()
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return frozenset(result)


def get_mode_switch_visibility() -> str:
    """Видимость кнопки переключения режима: public | testers | off. По умолчанию public."""
    raw = (os.getenv("MODE_SWITCH_VISIBILITY") or "public").strip().lower()
    if raw in ("public", "testers", "off"):
        return raw
    return "public"


def get_mode_switch_users() -> set[int]:
    """Telegram ID пользователей, которым показывается кнопка в режиме testers (из MODE_SWITCH_USERS)."""
    raw = (os.getenv("MODE_SWITCH_USERS") or "").strip()
    if not raw:
        return set()
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


def get_mode_switch_public() -> bool:
    """Кнопка переключения режима видна всем (1) или только PRO_TEST_USERS (0). По умолчанию 1. Устарело: используйте get_mode_switch_visibility()."""
    raw = os.getenv("MODE_SWITCH_PUBLIC", "1").strip()
    return raw in ("1", "true", "yes", "on")


def get_pro_test_users() -> frozenset[int]:
    """Telegram ID пользователей с тестовым доступом к PRO (из PRO_TEST_USERS). Устарело: для кнопки используйте get_mode_switch_users()."""
    raw = os.getenv("PRO_TEST_USERS", "").strip()
    if not raw:
        return frozenset()
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return frozenset(result)


def get_db_path() -> Path:
    """Получить путь к файлу базы данных."""
    return Path(__file__).resolve().parent / "users.db"
