"""Работа с SQLite: инициализация, миграция, CRUD, логирование запросов."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, List, Optional

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
        # Мягко добавить is_pro, если таблица уже была без него
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_pro" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_pro INTEGER DEFAULT 0")
            logger.info("Добавлена колонка users.is_pro")
        if "mode" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'free'")
            logger.info("Добавлена колонка users.mode")
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if "thread_id_free" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN thread_id_free TEXT")
            logger.info("Добавлена колонка users.thread_id_free")
        if "thread_id_pro" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN thread_id_pro TEXT")
            logger.info("Добавлена колонка users.thread_id_pro")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                request_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 1,
                response_time_ms INTEGER,
                mode TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        cursor = conn.execute("PRAGMA table_info(user_requests)")
        ur_columns = [row[1] for row in cursor.fetchall()]
        if "mode" not in ur_columns:
            conn.execute("ALTER TABLE user_requests ADD COLUMN mode TEXT")
            logger.info("Добавлена колонка user_requests.mode")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_requests_user_id_created_at "
            "ON user_requests(user_id, created_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_threads (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                UNIQUE(user_id, key)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_threads_user_id ON user_threads(user_id)"
        )
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if "pro_until" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN pro_until DATETIME")
            logger.info("Добавлена колонка users.pro_until")
        if "birth_time_unknown" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN birth_time_unknown INTEGER DEFAULT 0")
            logger.info("Добавлена колонка users.birth_time_unknown")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS surveys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                title TEXT,
                version INTEGER NOT NULL,
                questions_json TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS survey_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                bonus_days INTEGER DEFAULT 0,
                bonus_granted_at DATETIME,
                FOREIGN KEY(survey_id) REFERENCES surveys(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_survey_runs_user_survey ON survey_runs(user_id, survey_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS survey_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                question_key TEXT NOT NULL,
                answer_text TEXT,
                answer_choice TEXT,
                answer_number REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES survey_runs(id)
            )
        """)
        conn.commit()
    logger.info("База данных инициализирована: %s", db_path)
    ensure_seed_survey_onboarding_v1()


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
            "SELECT id, telegram_id, birth_date, birth_time, birth_place, thread_id, birth_time_unknown FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        if row:
            d = _row_to_user_dict(row)
            d["birth_time_unknown"] = bool(row[6]) if row[6] is not None else False
            return d

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
            "SELECT id, telegram_id, birth_date, birth_time, birth_place, thread_id, birth_time_unknown FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        d = _row_to_user_dict(row)
        d["birth_time_unknown"] = bool(row[6]) if row[6] is not None else False
        return d


def update_user_birth_data(
    telegram_id: int,
    birth_date: str,
    birth_time: Optional[str],
    birth_place: str,
    birth_time_unknown: bool = False,
) -> None:
    """Обновить данные рождения пользователя в users."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET birth_date = ?, birth_time = ?, birth_place = ?, birth_time_unknown = ? WHERE telegram_id = ?",
            (birth_date, birth_time, birth_place, 1 if birth_time_unknown else 0, telegram_id),
        )
        conn.commit()
    logger.info("Обновлены данные рождения: telegram_id=%s, birth_time_unknown=%s", telegram_id, birth_time_unknown)


def get_user_birth_data(telegram_id: int) -> Optional[dict[str, Any]]:
    """Вернуть birth_date, birth_time, birth_place, birth_time_unknown из users или None."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT birth_date, birth_time, birth_place, birth_time_unknown FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "birth_date": row[0],
            "birth_time": row[1],
            "birth_place": row[2],
            "birth_time_unknown": bool(row[3]) if row[3] is not None else False,
        }


def get_user_mode(telegram_id: int) -> str:
    """Режим пользователя из БД: 'free' или 'pro'. Учитывает pro_until (бонус PRO). По умолчанию 'free'."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT mode, pro_until FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cursor.fetchone()
        if not row:
            return "free"
        pro_until_raw = row[1] if len(row) > 1 else None
        if pro_until_raw:
            try:
                until = datetime.fromisoformat(pro_until_raw.replace("Z", "+00:00").split("+")[0].strip())
                if datetime.now() < until:
                    return "pro"
            except (ValueError, TypeError):
                pass
        return (row[0] or "free").lower().strip() or "free"


def set_user_mode(telegram_id: int, mode: str) -> None:
    """Установить режим пользователя: 'free' или 'pro'."""
    mode = (mode or "free").lower().strip()
    if mode not in ("free", "pro"):
        mode = "free"
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET mode = ? WHERE telegram_id = ?",
            (mode, telegram_id),
        )
        conn.commit()
    logger.info("Установлен режим %s для telegram_id=%s", mode, telegram_id)


def get_thread_id(user_id: int, key: str) -> Optional[str]:
    """
    Получить thread_id для пользователя и ключа из user_threads.
    user_id — telegram_id; key — например "free:forecast", "free:check_action", "pro:forecast", "pro:check_action".
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT thread_id FROM user_threads WHERE user_id = ? AND key = ?",
            (user_id, key),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        return row[0]


def set_thread_id(user_id: int, key: str, thread_id: str) -> None:
    """
    Сохранить thread_id для пользователя и ключа в user_threads.
    user_id — telegram_id; key — например "free:forecast", "pro:check_action".
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_threads (user_id, key, thread_id) VALUES (?, ?, ?)",
            (user_id, key, thread_id),
        )
        conn.commit()
    logger.info(
        "user_threads: user_id=%s key=%s thread_id=%s",
        user_id,
        key,
        thread_id[:16] + "..." if len(thread_id) > 16 else thread_id,
    )


def log_user_request(
    user_id: int,
    request_type: str,
    request_text: Optional[str] = None,
    success: int = 1,
    response_time_ms: Optional[int] = None,
    mode: Optional[str] = None,
) -> None:
    """
    Записать запрос пользователя в user_requests.
    user_id — внутренний users.id (из get_or_create_user(...)["id"]).
    request_type: today, tomorrow, check_action, favorable, topic, setdata.
    mode: 'free' или 'pro' для аналитики.
    """
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_requests (user_id, request_type, request_text, success, response_time_ms, mode)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, request_type, request_text, success, response_time_ms, (mode or "").lower() or None),
        )
        conn.commit()


# --------------- Опросники (surveys) ---------------

ONBOARDING_V1_CODE = "onboarding_v1"
ONBOARDING_V1_QUESTIONS = [
    {"key": "q1_first_impression", "type": "text", "text": "Какое первое впечатление от бота? (1–2 предложения)"},
    {"key": "q2_best_feature", "type": "choice", "text": "Какая функция полезнее всего?", "choices": ["Сегодня", "Завтра", "Проверить действие", "По теме"]},
    {"key": "q3_personalization", "type": "scale", "text": "Насколько ответы ощущаются персональными? (1–10)", "min": 1, "max": 10},
    {"key": "q4_ui_clarity", "type": "scale", "text": "Насколько понятен интерфейс бота? (1–10)", "min": 1, "max": 10},
    {"key": "q5_missing", "type": "text", "text": "Чего не хватает или что хотелось бы улучшить?"},
    {"key": "q6_frequency", "type": "choice", "text": "Как часто вы бы пользовались ботом?", "choices": ["Каждый день", "Пару раз в неделю", "Редко/по ситуации"]},
    {"key": "q7_willing_to_pay", "type": "choice", "text": "Готовы ли вы платить за PRO-версию? Если да — какой вариант комфортен?", "choices": ["Не готова платить", "99 ₽/мес", "199 ₽/мес", "299 ₽/мес", "499 ₽/мес"]},
    {"key": "q8_pay_for", "type": "choice", "text": "За что вы бы скорее всего платили?", "choices": ["Более точные советы", "Проверка действий", "Выбор дат", "Разбор отношений/денег/карьеры"]},
]


def ensure_seed_survey_onboarding_v1() -> None:
    """Вставить опрос onboarding_v1, если его ещё нет."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM surveys WHERE code = ?", (ONBOARDING_V1_CODE,))
        if cursor.fetchone():
            return
        conn.execute(
            """INSERT INTO surveys (code, title, version, questions_json, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (ONBOARDING_V1_CODE, "Онбординг v1", 1, json.dumps(ONBOARDING_V1_QUESTIONS, ensure_ascii=False)),
        )
        conn.commit()
    logger.info("Добавлен опрос %s", ONBOARDING_V1_CODE)


def get_active_survey_by_code(code: str) -> Optional[dict[str, Any]]:
    """Получить активный опрос по коду. Возвращает dict с id, code, title, version, questions_json (list)."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT id, code, title, version, questions_json FROM surveys WHERE code = ? AND is_active = 1",
            (code,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["questions"] = json.loads(d["questions_json"]) if d.get("questions_json") else []
        return d


def has_completed_survey(internal_user_id: int, survey_id: int) -> bool:
    """Пользователь уже завершил этот опрос (получал бонус не более одного раза за версию)."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM survey_runs WHERE user_id = ? AND survey_id = ? AND status = 'completed'",
            (internal_user_id, survey_id),
        )
        return cursor.fetchone() is not None


def create_survey_run(internal_user_id: int, survey_id: int) -> int:
    """Создать прохождение опроса. Возвращает run_id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO survey_runs (survey_id, user_id, status) VALUES (?, ?, 'in_progress')",
            (survey_id, internal_user_id),
        )
        conn.commit()
        return cursor.lastrowid


def save_survey_answer(
    run_id: int,
    question_key: str,
    answer_text: Optional[str] = None,
    answer_choice: Optional[str] = None,
    answer_number: Optional[float] = None,
) -> None:
    """Сохранить ответ на вопрос опроса."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO survey_answers (run_id, question_key, answer_text, answer_choice, answer_number)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, question_key, answer_text, answer_choice, answer_number),
        )
        conn.commit()


def complete_run_and_grant_bonus(
    run_id: int, internal_user_id: int, telegram_id: int, days: int = 3
) -> Optional[str]:
    """
    Пометить run как completed, выдать бонус PRO на days дней (продлеваем pro_until).
    Возвращает дату окончания PRO в формате DD.MM.YYYY или None при ошибке.
    Один completed run на (user_id, survey_id) — обеспечивается вызывающим кодом.
    """
    now = datetime.now()
    bonus_until = now + timedelta(days=days)
    bonus_until_str = bonus_until.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT pro_until FROM users WHERE id = ?",
            (internal_user_id,),
        )
        row = cursor.fetchone()
        current_until = row[0] if row and row[0] else None
        if current_until:
            try:
                current_dt = datetime.fromisoformat(current_until.replace("Z", "+00:00").split("+")[0].strip())
                if current_dt > now:
                    bonus_until = current_dt + timedelta(days=days)
                else:
                    bonus_until = now + timedelta(days=days)
                bonus_until_str = bonus_until.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass
        conn.execute(
            "UPDATE users SET pro_until = ? WHERE id = ?",
            (bonus_until_str, internal_user_id),
        )
        conn.execute(
            """UPDATE survey_runs SET status = 'completed', completed_at = ?, bonus_days = ?, bonus_granted_at = ?
               WHERE id = ?""",
            (now.strftime("%Y-%m-%d %H:%M:%S"), days, now.strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
        conn.commit()
    return bonus_until.strftime("%d.%m.%Y")


def abandon_survey_run(run_id: int) -> None:
    """Пометить прохождение опроса как abandoned."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE survey_runs SET status = 'abandoned' WHERE id = ?",
            (run_id,),
        )
        conn.commit()


# --------------- Совместимый API для handlers и assistant ---------------


def user_exists(telegram_id: int) -> bool:
    """Проверить, существует ли пользователь в новой таблице users."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone() is not None


def user_has_full_data(telegram_id: int) -> bool:
    """Проверить, заполнены ли у пользователя дата, время (или время неизвестно) и место рождения."""
    data = get_user_birth_data(telegram_id)
    if not data:
        return False
    has_date = bool(data.get("birth_date"))
    has_place = bool(data.get("birth_place"))
    has_time_or_unknown = bool(data.get("birth_time")) or bool(data.get("birth_time_unknown"))
    return has_date and has_place and has_time_or_unknown


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
    birth_time: Optional[str],
    birth_place: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    birth_time_unknown: bool = False,
) -> None:
    """Сохранить данные рождения (совместимость с handlers/start)."""
    get_or_create_user(telegram_id)
    update_user_birth_data(telegram_id, birth_date, birth_time, birth_place, birth_time_unknown=birth_time_unknown)


# --------------- Admin / статистика ---------------

# Часовой пояс для отображения "Последняя активность" в /admin
_ADMIN_DISPLAY_TZ = ZoneInfo("Europe/Paris")


def _parse_created_at_as_utc(val: Any) -> Optional[datetime]:
    """
    Парсит created_at из БД (TEXT 'YYYY-MM-DD HH:MM:SS' или ISO).
    SQLite хранит в UTC. Возвращает timezone-aware datetime (UTC) или None.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00").split("+")[0].strip()
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def get_admin_stats(exclude_telegram_ids: set[int]) -> dict[str, Any]:
    """
    Статистика для /admin: пользователи, активность, исключая exclude_telegram_ids (MODE_SWITCH_USERS).
    Возвращает: users_count, last_activity (DD.MM.YYYY HH:MM или "н/д"), last_activity_ago ("Xч Ym" или "н/д"),
    active_24h, requests_24h, last_activity_source ("user_requests" или "users").
    last_activity и last_activity_ago — из того же источника, что и requests_24h/active_24h: MAX(user_requests.created_at).
    Fallback: если user_requests пустая/отсутствует — MAX(users.created_at).
    """
    result: dict[str, Any] = {
        "users_count": 0,
        "last_activity": "н/д",
        "last_activity_ago": "н/д",
        "active_24h": 0,
        "requests_24h": "н/д",
        "last_activity_source": "users",
    }
    last_activity_dt: Optional[datetime] = None
    placeholders = ",".join("?" * len(exclude_telegram_ids)) if exclude_telegram_ids else ""
    params = list(exclude_telegram_ids) if exclude_telegram_ids else []

    try:
        with get_connection() as conn:
            if exclude_telegram_ids:
                cursor = conn.execute(
                    f"SELECT COUNT(*) FROM users WHERE telegram_id NOT IN ({placeholders})",
                    params,
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM users")
            row = cursor.fetchone()
            result["users_count"] = row[0] if row else 0

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_requests'"
            )
            has_ur_table = cursor.fetchone() is not None

            if has_ur_table:
                if exclude_telegram_ids:
                    cursor = conn.execute(
                        """SELECT COUNT(DISTINCT u.telegram_id), COUNT(*) FROM user_requests ur
                           JOIN users u ON ur.user_id = u.id
                           WHERE u.telegram_id NOT IN ({}) AND ur.created_at >= datetime('now', '-24 hours')""".format(
                            placeholders
                        ),
                        params,
                    )
                else:
                    cursor = conn.execute(
                        """SELECT COUNT(DISTINCT u.telegram_id), COUNT(*) FROM user_requests ur
                           JOIN users u ON ur.user_id = u.id
                           WHERE ur.created_at >= datetime('now', '-24 hours')"""
                    )
                row = cursor.fetchone()
                if row:
                    result["active_24h"] = row[0] or 0
                    result["requests_24h"] = row[1] or 0
                else:
                    result["requests_24h"] = 0

                if exclude_telegram_ids:
                    cursor = conn.execute(
                        """SELECT MAX(ur.created_at) FROM user_requests ur
                           JOIN users u ON ur.user_id = u.id
                           WHERE u.telegram_id NOT IN ({})""".format(placeholders),
                        params,
                    )
                else:
                    cursor = conn.execute(
                        """SELECT MAX(ur.created_at) FROM user_requests ur JOIN users u ON ur.user_id = u.id"""
                    )
                row = cursor.fetchone()
                val = row[0] if row and row[0] else None
                if val:
                    last_activity_dt = _parse_created_at_as_utc(val)
                    if last_activity_dt:
                        result["last_activity_source"] = "user_requests"
                        local_dt = last_activity_dt.astimezone(_ADMIN_DISPLAY_TZ)
                        result["last_activity"] = local_dt.strftime("%d.%m.%Y %H:%M")

            if last_activity_dt is None:
                result["last_activity_source"] = "users"
                if exclude_telegram_ids:
                    cursor = conn.execute(
                        f"""SELECT MAX(created_at) FROM users WHERE telegram_id NOT IN ({placeholders})""",
                        params,
                    )
                else:
                    cursor = conn.execute("SELECT MAX(created_at) FROM users")
                row = cursor.fetchone()
                val = row[0] if row and row[0] else None
                if val:
                    last_activity_dt = _parse_created_at_as_utc(val)
                    if last_activity_dt:
                        local_dt = last_activity_dt.astimezone(_ADMIN_DISPLAY_TZ)
                        result["last_activity"] = local_dt.strftime("%d.%m.%Y %H:%M")

            if not has_ur_table:
                result["requests_24h"] = "н/д"
    except Exception as e:
        logger.warning("get_admin_stats error: %s", e)
        result["last_activity"] = "н/д"
        result["last_activity_ago"] = "н/д"
        result["requests_24h"] = "н/д"
        return result

    if last_activity_dt:
        try:
            now_utc = datetime.now(timezone.utc)
            delta = now_utc - last_activity_dt
            total_minutes = int(delta.total_seconds() / 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            result["last_activity_ago"] = f"{hours}ч {minutes}м"
        except (TypeError, ValueError):
            result["last_activity_ago"] = "н/д"
    return result
