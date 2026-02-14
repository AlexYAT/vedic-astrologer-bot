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
    """Получить ID ассистента OpenAI."""
    assistant_id = os.getenv("ASSISTANT_ID")
    if not assistant_id:
        raise ValueError("ASSISTANT_ID не задан в переменных окружения или .env")
    return assistant_id


def get_db_path() -> Path:
    """Получить путь к файлу базы данных."""
    return Path(__file__).resolve().parent / "users.db"
