"""
Минимальные проверки БД: init_db, get_or_create_user, миграция из legacy, log_user_request.
Запуск из корня проекта: python scripts/check_db.py
Использует временные файлы БД, не трогает users.db.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

# Добавить корень проекта в path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

import db


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        # 1) init_db не падает
        db.init_db(db_path)
        print("OK: init_db() выполнен")

        # 2) Пользователь без данных создаётся
        u = db.get_or_create_user(telegram_id=12345)
        assert u is not None
        assert u.get("telegram_id") == 12345
        assert u.get("id") is not None
        print("OK: пользователь без данных создаётся, id =", u["id"])

        # 3) Данные сохраняются и читаются
        db.update_user_birth_data(12345, "01.01.1990", "12:00", "Москва")
        data = db.get_user_birth_data(12345)
        assert data and data.get("birth_date") == "01.01.1990"
        assert db.user_has_full_data(12345)
        print("OK: данные рождения сохраняются и читаются")

        # 4) Логирование запросов создаёт записи
        internal_id = u["id"]
        db.log_user_request(internal_id, "today", request_text=None, success=1, response_time_ms=150)
        db.log_user_request(internal_id, "check_action", request_text="подписать договор", success=0, response_time_ms=None)

        with db.get_connection() as conn:
            cur = conn.execute(
                "SELECT request_type, success, response_time_ms FROM user_requests WHERE user_id = ? ORDER BY id",
                (internal_id,),
            )
            rows = cur.fetchall()
        assert len(rows) >= 2
        types = {r[0] for r in rows}
        assert "today" in types and "check_action" in types
        print("OK: логирование запросов создаёт записи в user_requests")

        # 5) Миграция из старой таблицы: создаём БД со старой схемой, init_db переименует в users_legacy
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f2:
            legacy_path = Path(f2.name)
        try:
            conn = sqlite3.connect(legacy_path)
            conn.execute("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    birth_date TEXT, birth_time TEXT, birth_place TEXT,
                    thread_id TEXT, created_at TEXT, updated_at TEXT
                )
            """)
            conn.execute(
                "INSERT INTO users (user_id, birth_date, birth_time, birth_place) VALUES (?, ?, ?, ?)",
                (88888, "15.03.1985", "10:30", "Казань"),
            )
            conn.commit()
            conn.close()
            db.init_db(legacy_path)
            u_legacy = db.get_or_create_user(telegram_id=88888)
            assert u_legacy.get("birth_date") == "15.03.1985" and u_legacy.get("birth_place") == "Казань"
            print("OK: данные из users_legacy подхватываются при get_or_create_user")
        finally:
            try:
                legacy_path.unlink(missing_ok=True)
            except OSError:
                pass

        print("\nВсе проверки пройдены.")
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
