"""
Пример безопасного чтения из users.db в режиме только для чтения.

ВАЖНО:
- SQLite поддерживает множественные читатели одновременно
- Чтение не блокирует запись и наоборот
- Используйте режим 'ro' (read-only) для гарантии безопасности
"""

import sqlite3
from pathlib import Path

# Путь к базе данных
DB_PATH = Path(__file__).parent.parent / "users.db"


def read_users_safe():
    """
    Безопасное чтение из БД в режиме только для чтения.
    
    Использует URI-подключение с mode=ro для гарантии,
    что случайная запись не повредит базу.
    """
    # Вариант 1: URI с mode=ro (рекомендуется)
    db_uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row  # Для удобного доступа к колонкам по имени
    
    try:
        cursor = conn.execute("SELECT telegram_id, birth_date, birth_time, birth_place FROM users LIMIT 10")
        rows = cursor.fetchall()
        
        print(f"Найдено пользователей: {len(rows)}")
        for row in rows:
            print(f"  telegram_id={row['telegram_id']}, birth_date={row['birth_date']}")
            
    finally:
        conn.close()


def read_users_simple():
    """
    Простое чтение (без явного mode=ro).
    
    Работает безопасно, если вы не выполняете операции записи.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        cursor = conn.execute("SELECT COUNT(*) as count FROM users")
        count = cursor.fetchone()['count']
        print(f"Всего пользователей в БД: {count}")
        
        # Пример чтения статистики
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN mode = 'pro' THEN 1 ELSE 0 END) as pro_count,
                SUM(CASE WHEN pro_until IS NOT NULL THEN 1 ELSE 0 END) as bonus_pro_count
            FROM users
        """)
        stats = cursor.fetchone()
        print(f"  Всего: {stats['total']}")
        print(f"  PRO: {stats['pro_count']}")
        print(f"  PRO (бонус): {stats['bonus_pro_count']}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== Безопасное чтение (mode=ro) ===")
    read_users_safe()
    
    print("\n=== Простое чтение ===")
    read_users_simple()
