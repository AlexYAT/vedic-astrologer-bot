"""Работа с SQLite: инициализация, миграция, CRUD, логирование запросов."""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Путь к БД (будет переопределён из config при запуске)
_DB_PATH: Optional[Path] = None

# Имя старой таблицы после переименования (lazy migration)
_LEGACY_TABLE = "users_legacy"


def init_db(db_path: Path) -> None:
    """
    Инициализация БД: при наличии старой таблицы users (user_id PK) — переименовать в users_legacy,
    создать новые таблицы users и user_requests.
    """
    global _DB_PATH
    _DB_PATH = db_path
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        if cursor.fetchone():
            cursor = conn.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in cursor.fetchall()]
            # Старая схема: user_id как PK, нет telegram_id
            if "user_id" in columns and "telegram_id" not in columns:
                conn.execute(f"ALTER TABLE users RENAME TO {_LEGACY_TABLE}")
                conn.commit()
                logger.info("Таблица users переименована в %s для миграции", _LEGACY_TABLE)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                birth_date TEXT,
                birth_time TEXT,
                birth_place TEXT,
                thread_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_pro INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                request_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 1,
                response_time_ms INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_requests_user_id_created_at "
            "ON user_requests(user_id, created_at)"
        )
        conn.commit()
    logger.info("База данных инициализирована: %s", db_path)


def get_connection() -> sqlite3.Connection:
    """Получить соединение с БД."""
    if _DB_PATH is None:
        raise RuntimeError("База данных не инициализирована. Вызовите init_db().")
    return sqlite3.connect(_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)


def _row_to_user_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Преобразовать строку users в dict с ключами, ожидаемыми handlers/assistant."""
    d = dict(row)
    # Для совместимости: telegram_id доступен как user_id в старом смысле (для assistant)
    d["user_id"] = d.get("telegram_id")
    return d


def _legacy_table_exists(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_LEGACY_TABLE,),
    )
    return cursor.fetchone() is not None


def _migrate_from_legacy(conn: sqlite3.Connection, telegram_id: int) -> Optional[dict[str, Any]]:
    """Прочитать данные из users_legacy по user_id (= telegram_id). Не удаляет из legacy."""
    if not _legacy_table_exists(conn):
        return None
    cursor = conn.execute(
        "SELECT birth_date, birth_time, birth_place, thread_id FROM users_legacy WHERE user_id = ?",
        (telegram_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    birth_date, birth_time, birth_place, thread_id = row
    return {
        "birth_date": birth_date,
        "birth_time": birth_time,
        "birth_place": birth_place,
        "thread_id": thread_id,
    }


def get_or_create_user(telegram_id: int) -> dict[str, Any]:
    """
    Получить или создать пользователя в новой таблице users.
    Если записи нет — при наличии users_legacy переносит данные (lazy migration).
    Возвращает dict с ключами: id, telegram_id, birth_date, birth_time, birth_place, thread_id, user_id (=telegram_id).
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT id, telegram_id, birth_date, birth_time, birth_place, thread_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        if row:
            return _row_to_user_dict(row)

        legacy = _migrate_from_legacy(conn, telegram_id)
        if legacy:
            conn.execute(
                """INSERT INTO users (telegram_id, birth_date, birth_time, birth_place, thread_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    telegram_id,
                    legacy.get("birth_date"),
                    legacy.get("birth_time"),
                    legacy.get("birth_place"),
                    legacy.get("thread_id"),
                ),
            )
            logger.info("Мигрирован пользователь из users_legacy: telegram_id=%s", telegram_id)
        else:
            conn.execute(
                "INSERT INTO users (telegram_id) VALUES (?)",
                (telegram_id,),
            )
        conn.commit()
        cursor = conn.execute(
            "SELECT id, telegram_id, birth_date, birth_time, birth_place, thread_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        return _row_to_user_dict(row)


def update_user_birth_data(
    telegram_id: int,
    birth_date: str,
    birth_time: str,
    birth_place: str,
) -> None:
    """Обновить данные рождения пользователя в users."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET birth_date = ?, birth_time = ?, birth_place = ? WHERE telegram_id = ?",
            (birth_date, birth_time, birth_place, telegram_id),
        )
        conn.commit()
    logger.info("Обновлены данные рождения: telegram_id=%s", telegram_id)


def get_user_birth_data(telegram_id: int) -> Optional[dict[str, Any]]:
    """Вернуть birth_date, birth_time, birth_place из users или None."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT birth_date, birth_time, birth_place FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "birth_date": row[0],
            "birth_time": row[1],
            "birth_place": row[2],
        }


def log_user_request(
    user_id: int,
    request_type: str,
    request_text: Optional[str] = None,
    success: int = 1,
    response_time_ms: Optional[int] = None,
) -> None:
    """
    Записать запрос пользователя в user_requests.
    user_id — внутренний users.id (из get_or_create_user(...)["id"]).
    request_type: today, tomorrow, check_action, favorable, topic, setdata.
    """
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_requests (user_id, request_type, request_text, success, response_time_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, request_type, request_text, success, response_time_ms),
        )
        conn.commit()


# --------------- Совместимый API для handlers и assistant ---------------


def user_exists(telegram_id: int) -> bool:
    """Проверить, существует ли пользователь в новой таблице users."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone() is not None


def user_has_full_data(telegram_id: int) -> bool:
    """Проверить, заполнены ли у пользователя дата, время и место рождения."""
    data = get_user_birth_data(telegram_id)
    if not data:
        return False
    return bool(
        data.get("birth_date") and data.get("birth_time") and data.get("birth_place")
    )


def get_user(telegram_id: int) -> Optional[dict[str, Any]]:
    """
    Получить данные пользователя по telegram_id.
    Возвращает dict с id, telegram_id, user_id (=telegram_id), birth_date, birth_time, birth_place, thread_id.
    Если пользователя нет — создаёт через get_or_create_user и возвращает.
    """
    return get_or_create_user(telegram_id)


def create_user(telegram_id: int) -> None:
    """Создать или получить пользователя (совместимость с handlers)."""
    get_or_create_user(telegram_id)


def update_user(
    telegram_id: int,
    birth_date: Optional[str] = None,
    birth_time: Optional[str] = None,
    birth_place: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    """Обновить данные пользователя. Используются только переданные поля (совместимость с assistant)."""
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
    if thread_id is not None:
        updates.append("thread_id = ?")
        params.append(thread_id)
    if not updates:
        return
    params.append(telegram_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?",
            params,
        )
        conn.commit()
    logger.info("Обновлён пользователь: telegram_id=%s", telegram_id)


def save_user_data(
    telegram_id: int,
    birth_date: str,
    birth_time: str,
    birth_place: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> None:
    """Сохранить данные рождения (совместимость с handlers/start)."""
    get_or_create_user(telegram_id)
    update_user_birth_data(telegram_id, birth_date, birth_time, birth_place)
