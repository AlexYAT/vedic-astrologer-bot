"""Работа с SQLite: инициализация, CRUD операции."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Путь к БД (будет переопределён из config при запуске)
_DB_PATH: Optional[Path] = None


def init_db(db_path: Path) -> None:
    """Инициализация базы данных и создание таблицы users, если её нет."""
    global _DB_PATH
    _DB_PATH = db_path
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                birth_date TEXT,
                birth_time TEXT,
                birth_place TEXT,
                phone TEXT,
                email TEXT,
                thread_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.info("База данных инициализирована: %s", db_path)


def get_connection() -> sqlite3.Connection:
    """Получить соединение с БД."""
    if _DB_PATH is None:
        raise RuntimeError("База данных не инициализирована. Вызовите init_db().")
    return sqlite3.connect(_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)


def user_exists(user_id: int) -> bool:
    """Проверить, существует ли пользователь в БД."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None


def user_has_full_data(user_id: int) -> bool:
    """Проверить, заполнены ли у пользователя обязательные данные (дата, время, место рождения)."""
    with get_connection() as conn:
        cursor = conn.execute(
            """SELECT birth_date, birth_time, birth_place FROM users WHERE user_id = ?""",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        birth_date, birth_time, birth_place = row
        return bool(birth_date and birth_time and birth_place)


def get_user(user_id: int) -> Optional[dict]:
    """Получить данные пользователя по user_id."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def create_user(user_id: int) -> None:
    """Создать запись пользователя."""
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users (user_id, created_at, updated_at)
               VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (user_id,)
        )
        conn.commit()
    logger.info("Создан пользователь: user_id=%s", user_id)


def update_user(
    user_id: int,
    birth_date: Optional[str] = None,
    birth_time: Optional[str] = None,
    birth_place: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    """Обновить данные пользователя. Передаются только изменяемые поля."""
    updates = []
    params = []

    if birth_date is not None:
        updates.append("birth_date = ?")
        params.append(birth_date)
    if birth_time is not None:
        updates.append("birth_time = ?")
        params.append(birth_time)
    if birth_place is not None:
        updates.append("birth_place = ?")
        params.append(birth_place)
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone)
    if email is not None:
        updates.append("email = ?")
        params.append(email)
    if thread_id is not None:
        updates.append("thread_id = ?")
        params.append(thread_id)

    if not updates:
        return

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(user_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
            params
        )
        conn.commit()
    logger.info("Обновлён пользователь: user_id=%s", user_id)


def save_user_data(
    user_id: int,
    birth_date: str,
    birth_time: str,
    birth_place: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> None:
    """Сохранить полные данные пользователя (дата, время, место, контакты)."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users (user_id, birth_date, birth_time, birth_place, phone, email, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   birth_date = excluded.birth_date,
                   birth_time = excluded.birth_time,
                   birth_place = excluded.birth_place,
                   phone = COALESCE(excluded.phone, phone),
                   email = COALESCE(excluded.email, email),
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, birth_date, birth_time, birth_place, phone, email)
        )
        conn.commit()
    logger.info("Сохранены данные пользователя: user_id=%s", user_id)
