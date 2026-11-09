import os
import secrets
import string
from pathlib import Path
import aiosqlite
from config import DB_PATH

def _db_file():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

async def connect():
    db = await aiosqlite.connect(_db_file())
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db

async def init_db():
    async with await connect() as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT NOT NULL,
            joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_blocked INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            content_type TEXT NOT NULL,
            file_id TEXT,
            body TEXT,
            price REAL NOT NULL DEFAULT 0,
            is_free INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            protect INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            join_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            holder TEXT NOT NULL,
            account TEXT NOT NULL,
            instructions TEXT DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            content_id INTEGER NOT NULL,
            method_id INTEGER NOT NULL,
            transaction_ref TEXT NOT NULL,
            proof_file_id TEXT,
            proof_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id),
            FOREIGN KEY(content_id) REFERENCES contents(id),
            FOREIGN KEY(method_id) REFERENCES payment_methods(id)
        );
        CREATE TABLE IF NOT EXISTS purchases (
            user_id INTEGER NOT NULL,
            content_id INTEGER NOT NULL,
            payment_id INTEGER,
            purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, content_id),
            FOREIGN KEY(user_id) REFERENCES users(telegram_id),
            FOREIGN KEY(content_id) REFERENCES contents(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS broadcast_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total INTEGER NOT NULL,
            sent INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        await db.commit()

async def execute(query, params=()):
    async with await connect() as db:
        cur = await db.execute(query, params)
        await db.commit()
        return cur.lastrowid

async def fetchone(query, params=()):
    async with await connect() as db:
        cur = await db.execute(query, params)
        return await cur.fetchone()

async def fetchall(query, params=()):
    async with await connect() as db:
        cur = await db.execute(query, params)
        return await cur.fetchall()

async def save_user(user_id: int, username: str | None, first_name: str):
    await execute("""
        INSERT INTO users(telegram_id, username, first_name)
        VALUES(?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
          username=excluded.username,
          first_name=excluded.first_name,
          last_seen=CURRENT_TIMESTAMP,
          is_blocked=0
    """, (user_id, username, first_name))

async def set_blocked(user_id: int, blocked: bool):
    await execute("UPDATE users SET is_blocked=? WHERE telegram_id=?", (int(blocked), user_id))

async def create_content(title, description, content_type, file_id, body, price, protect=True):
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(9))
    while await fetchone("SELECT id FROM contents WHERE code=?", (code,)):
        code = "".join(secrets.choice(alphabet) for _ in range(9))
    cid = await execute("""
        INSERT INTO contents(code,title,description,content_type,file_id,body,price,is_free,protect)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (code, title, description, content_type, file_id, body, float(price),
          int(float(price) <= 0), int(protect)))
    return await fetchone("SELECT * FROM contents WHERE id=?", (cid,))

async def get_content(content_id: int):
    return await fetchone("SELECT * FROM contents WHERE id=?", (content_id,))

async def get_content_by_code(code: str):
    return await fetchone("SELECT * FROM contents WHERE code=? AND active=1", (code,))

async def list_contents(active_only=True, limit=30):
    if active_only:
        return await fetchall("SELECT * FROM contents WHERE active=1 ORDER BY id DESC LIMIT ?", (limit,))
    return await fetchall("SELECT * FROM contents ORDER BY id DESC LIMIT ?", (limit,))

async def delete_content(content_id: int):
    await execute("DELETE FROM purchases WHERE content_id=?", (content_id,))
    await execute("DELETE FROM payments WHERE content_id=?", (content_id,))
    await execute("DELETE FROM contents WHERE id=?", (content_id,))

async def toggle_content(content_id: int):
    await execute("UPDATE contents SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (content_id,))

async def update_content_price(content_id: int, price: float):
    await execute("UPDATE contents SET price=?, is_free=? WHERE id=?",
                  (price, int(price <= 0), content_id))

async def update_content_info(content_id: int, title: str, description: str):
    await execute("UPDATE contents SET title=?, description=? WHERE id=?",
                  (title, description, content_id))

async def has_purchase(user_id: int, content_id: int) -> bool:
    row = await fetchone("SELECT 1 FROM purchases WHERE user_id=? AND content_id=?",
                         (user_id, content_id))
    return row is not None

async def add_channel(chat_id, title, join_url):
    return await execute("INSERT INTO channels(chat_id,title,join_url) VALUES(?,?,?)",
                         (str(chat_id), title, join_url))

async def get_channels(enabled_only=True):
    if enabled_only:
        return await fetchall("SELECT * FROM channels WHERE enabled=1 ORDER BY id")
    return await fetchall("SELECT * FROM channels ORDER BY id")

async def delete_channel(channel_id: int):
    await execute("DELETE FROM channels WHERE id=?", (channel_id,))

async def add_payment_method(name, holder, account, instructions):
    return await execute("""
        INSERT INTO payment_methods(name,holder,account,instructions)
        VALUES(?,?,?,?)
    """, (name, holder, account, instructions))

async def get_payment_methods(enabled_only=True):
    if enabled_only:
        return await fetchall("SELECT * FROM payment_methods WHERE enabled=1 ORDER BY id")
    return await fetchall("SELECT * FROM payment_methods ORDER BY id")

async def delete_payment_method(method_id: int):
    # Soft-delete: preserve historical payment references and any in-progress checkout.
    await execute("UPDATE payment_methods SET enabled=0 WHERE id=?", (method_id,))

async def toggle_payment_method(method_id: int):
    await execute("UPDATE payment_methods SET enabled=1-enabled WHERE id=?", (method_id,))

async def create_payment(user_id, content_id, method_id, transaction_ref, proof_file_id, proof_type):
    order = "LCH-" + "".join(secrets.choice(string.digits) for _ in range(8))
    pid = await execute("""
        INSERT INTO payments(order_code,user_id,content_id,method_id,transaction_ref,proof_file_id,proof_type)
        VALUES(?,?,?,?,?,?,?)
    """, (order, user_id, content_id, method_id, transaction_ref, proof_file_id, proof_type))
    return await fetchone("SELECT * FROM payments WHERE id=?", (pid,))

async def get_payment(payment_id: int):
    return await fetchone("SELECT * FROM payments WHERE id=?", (payment_id,))

async def review_payment(payment_id: int, approved: bool):
    status = "approved" if approved else "rejected"
    await execute("UPDATE payments SET status=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",
                  (status, payment_id))
    payment = await get_payment(payment_id)
    if approved and payment:
        await execute("""
            INSERT OR IGNORE INTO purchases(user_id,content_id,payment_id)
            VALUES(?,?,?)
        """, (payment["user_id"], payment["content_id"], payment_id))
    return payment

async def get_user_ids(active_only=True):
    if active_only:
        rows = await fetchall("SELECT telegram_id FROM users WHERE is_blocked=0")
    else:
        rows = await fetchall("SELECT telegram_id FROM users")
    return [r["telegram_id"] for r in rows]

async def count(table: str, where: str = ""):
    allowed = {"users", "contents", "channels", "payments", "purchases"}
    if table not in allowed:
        raise ValueError("Invalid table")
    suffix = f" WHERE {where}" if where else ""
    row = await fetchone(f"SELECT COUNT(*) AS n FROM {table}{suffix}")
    return int(row["n"])

async def get_stats():
    return {
        "users": await count("users", "is_blocked=0"),
        "contents": await count("contents", "active=1"),
        "pending": await count("payments", "status='pending'"),
        "approved": await count("payments", "status='approved'"),
        "purchases": await count("purchases"),
    }

async def save_broadcast(total, sent, failed, status="completed"):
    await execute("INSERT INTO broadcast_logs(total,sent,failed,status) VALUES(?,?,?,?)",
                  (total, sent, failed, status))

async def set_setting(key: str, value: str):
    await execute("""
        INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))

async def get_setting(key: str, default: str = ""):
    row = await fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default
