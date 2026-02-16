"""
Настройка логирования: консоль + файл с ротацией по дням.
Без внешних зависимостей, только стандартный logging.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> None:
    """
    Настраивает root logger: консоль + файл с ротацией по дням.
    Создаёт папку logs/ при необходимости.
    Уровень: INFO по умолчанию, DEBUG если задан env LOG_LEVEL=DEBUG.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    # Очищаем существующие handlers, чтобы не дублировать при повторном вызове
    root.handlers.clear()

    # Консоль
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Файл с ротацией по полуночи, хранить 14 дней
    file_handler = TimedRotatingFileHandler(
        filename=str(LOG_FILE),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
