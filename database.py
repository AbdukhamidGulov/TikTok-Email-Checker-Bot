import aiosqlite
from datetime import datetime

DB_NAME = "tiktok_checker.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT,
                status TEXT DEFAULT 'pending',
                updated_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_email_user ON emails (email, user_id)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                proxy_string TEXT,
                status TEXT DEFAULT 'active',
                error_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_proxy_user ON proxies (proxy_string, user_id)
        """)
        await db.commit()


async def add_emails(user_id: int, emails: list):
    async with aiosqlite.connect(DB_NAME) as db:
        data = [(user_id, email, datetime.now()) for email in emails]
        await db.executemany("""
            INSERT OR IGNORE INTO emails (user_id, email, updated_at)
            VALUES (?, ?, ?)
        """, data)
        await db.commit()


async def get_pending_emails(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT email FROM emails 
            WHERE user_id = ? AND status = 'pending'
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def update_email_status(user_id: int, email: str, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE emails 
            SET status = ?, updated_at = ? 
            WHERE user_id = ? AND email = ?
        """, (status, datetime.now(), user_id, email))
        await db.commit()


async def add_proxies(user_id: int, proxies: list):
    async with aiosqlite.connect(DB_NAME) as db:
        data = [(user_id, p) for p in proxies]
        await db.executemany("""
            INSERT OR IGNORE INTO proxies (user_id, proxy_string)
            VALUES (?, ?)
        """, data)
        await db.commit()


async def get_active_proxies(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT proxy_string FROM proxies 
            WHERE user_id = ? AND status = 'active'
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_stats(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END), 0) as valid,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) as pending,
                COALESCE(SUM(CASE WHEN status = 'invalid' THEN 1 ELSE 0 END), 0) as invalid,
                COUNT(email) as total 
            FROM emails 
            WHERE user_id = ?
        """, (user_id,)) as cursor:
            # порядок: valid, pending, invalid, total
            row = await cursor.fetchone()

            if row is None:
                return 0, 0, 0, 0

                # Возвращаем в порядке: total, valid, pending, invalid
            valid, pending, invalid, total = row
            return total, valid, pending, invalid


async def get_emails_by_status(user_id: int, status: str):
    """Получает все почты пользователя по заданному статусу ('valid', 'invalid', 'pending')"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT email FROM emails 
            WHERE user_id = ? AND status = ?
        """, (user_id, status)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def clear_data(user_id: int, table: str):
    valid_tables = ["emails", "proxies"]
    if table not in valid_tables:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        await db.commit()
