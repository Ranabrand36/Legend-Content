import json
from contextlib import asynccontextmanager
import secrets
import string
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from config import DATABASE_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 telegram_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT NOT NULL,
 joined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 is_blocked SMALLINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contents (
 id BIGSERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 description TEXT DEFAULT '', content_type TEXT NOT NULL, file_id TEXT, body TEXT,
 price DOUBLE PRECISION NOT NULL DEFAULT 0, is_free SMALLINT NOT NULL DEFAULT 1,
 active SMALLINT NOT NULL DEFAULT 1, protect SMALLINT NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS channels (
 id BIGSERIAL PRIMARY KEY, chat_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 join_url TEXT NOT NULL, enabled SMALLINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payment_methods (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, holder TEXT NOT NULL,
 account TEXT NOT NULL, instructions TEXT DEFAULT '', enabled SMALLINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments (
 id BIGSERIAL PRIMARY KEY, order_code TEXT UNIQUE NOT NULL,
 user_id BIGINT NOT NULL REFERENCES users(telegram_id),
 content_id BIGINT NOT NULL REFERENCES contents(id),
 method_id BIGINT NOT NULL REFERENCES payment_methods(id),
 transaction_ref TEXT NOT NULL, proof_file_id TEXT, proof_type TEXT,
 status TEXT NOT NULL DEFAULT 'pending',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, reviewed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS purchases (
 user_id BIGINT NOT NULL REFERENCES users(telegram_id),
 content_id BIGINT NOT NULL REFERENCES contents(id), payment_id BIGINT,
 purchased_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(user_id, content_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broadcast_logs (
 id BIGSERIAL PRIMARY KEY, total INTEGER NOT NULL, sent INTEGER NOT NULL,
 failed INTEGER NOT NULL, status TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_payments_status_created ON payments(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contents_active_id ON contents(active, id DESC);
"""

_pool = None


def _sql(query):
    return query.replace("INSERT OR IGNORE INTO", "INSERT INTO").replace("?", "%s")

@asynccontextmanager
async def connect():
    global _pool
    if _pool is None:
        await init_db()
    async with _pool.connection() as conn:
        yield conn


async def init_db():
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=10,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=False,
        )
        await _pool.open(wait=True)
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    await cur.execute(statement)


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

async def execute(query, params=()):
    q = _sql(query.strip())
    # Preserve the old helper contract: INSERTs into serial-ID tables return their new ID.
    import re
    match = re.match(r"INSERT\s+INTO\s+(\w+)", q, re.I)
    id_tables = {"contents", "channels", "payment_methods", "payments", "broadcast_logs"}
    if match and match.group(1).lower() in id_tables and "RETURNING" not in q.upper():
        q += " RETURNING id"
    async with connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute(q, params)
            if "RETURNING id" in q.upper():
                row = await cur.fetchone()
                return row["id"] if row else None
            return cur.rowcount

async def fetchone(query, params=()):
    async with connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_sql(query), params)
            return await cur.fetchone()

async def fetchall(query, params=()):
    async with connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_sql(query), params)
            return await cur.fetchall()

async def save_user(user_id: int, username: str | None, first_name: str):
    await execute("""INSERT INTO users(telegram_id,username,first_name) VALUES(%s,%s,%s)
      ON CONFLICT(telegram_id) DO UPDATE SET username=EXCLUDED.username,
      first_name=EXCLUDED.first_name,last_seen=CURRENT_TIMESTAMP,is_blocked=0""",
      (user_id, username, first_name))

async def set_blocked(user_id: int, blocked: bool):
    await execute("UPDATE users SET is_blocked=%s WHERE telegram_id=%s", (int(blocked), user_id))

async def create_content(title, description, content_type, file_id, body, price, protect=True):
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(9))
    while await fetchone("SELECT id FROM contents WHERE code=%s", (code,)):
        code = "".join(secrets.choice(alphabet) for _ in range(9))
    cid = await execute("""INSERT INTO contents(code,title,description,content_type,file_id,body,price,is_free,protect)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      (code,title,description,content_type,file_id,body,float(price),int(float(price)<=0),int(protect)))
    return await fetchone("SELECT * FROM contents WHERE id=%s", (cid,))

async def get_content(content_id): return await fetchone("SELECT * FROM contents WHERE id=%s",(content_id,))
async def get_content_by_code(code): return await fetchone("SELECT * FROM contents WHERE code=%s AND active=1",(code,))

async def list_contents(active_only=True, limit=30):
    q="SELECT * FROM contents WHERE active=1 ORDER BY id DESC LIMIT %s" if active_only else "SELECT * FROM contents ORDER BY id DESC LIMIT %s"
    return await fetchall(q,(limit,))

async def delete_content(content_id):
    await execute("DELETE FROM purchases WHERE content_id=%s",(content_id,))
    await execute("DELETE FROM payments WHERE content_id=%s",(content_id,))
    await execute("DELETE FROM contents WHERE id=%s",(content_id,))

async def toggle_content(content_id):
    await execute("UPDATE contents SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=%s",(content_id,))

async def update_content_price(content_id,price):
    await execute("UPDATE contents SET price=%s,is_free=%s WHERE id=%s",(price,int(price<=0),content_id))

async def update_content_info(content_id,title,description):
    await execute("UPDATE contents SET title=%s,description=%s WHERE id=%s",(title,description,content_id))

async def has_purchase(user_id,content_id):
    return await fetchone("SELECT 1 FROM purchases WHERE user_id=%s AND content_id=%s",(user_id,content_id)) is not None

async def add_channel(chat_id,title,join_url):
    return await execute("INSERT INTO channels(chat_id,title,join_url) VALUES(%s,%s,%s)",(str(chat_id),title,join_url))
async def get_channels(enabled_only=True):
    return await fetchall("SELECT * FROM channels WHERE enabled=1 ORDER BY id" if enabled_only else "SELECT * FROM channels ORDER BY id")
async def delete_channel(channel_id): await execute("DELETE FROM channels WHERE id=%s",(channel_id,))

async def add_payment_method(name,holder,account,instructions):
    return await execute("INSERT INTO payment_methods(name,holder,account,instructions) VALUES(%s,%s,%s,%s)",(name,holder,account,instructions))
async def get_payment_methods(enabled_only=True):
    return await fetchall("SELECT * FROM payment_methods WHERE enabled=1 ORDER BY id" if enabled_only else "SELECT * FROM payment_methods ORDER BY id")
async def delete_payment_method(method_id): await execute("UPDATE payment_methods SET enabled=0 WHERE id=%s",(method_id,))
async def toggle_payment_method(method_id): await execute("UPDATE payment_methods SET enabled=1-enabled WHERE id=%s",(method_id,))

async def create_payment(user_id,content_id,method_id,transaction_ref,proof_file_id,proof_type):
    order="LCH-"+"".join(secrets.choice(string.digits) for _ in range(8))
    pid=await execute("""INSERT INTO payments(order_code,user_id,content_id,method_id,transaction_ref,proof_file_id,proof_type)
      VALUES(%s,%s,%s,%s,%s,%s,%s)""",(order,user_id,content_id,method_id,transaction_ref,proof_file_id,proof_type))
    return await get_payment(pid)

async def get_payment(payment_id): return await fetchone("SELECT * FROM payments WHERE id=%s",(payment_id,))

async def review_payment(payment_id,approved):
    status="approved" if approved else "rejected"
    async with connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE payments SET status=%s,reviewed_at=CURRENT_TIMESTAMP WHERE id=%s AND status='pending'",(status,payment_id))
            await cur.execute("SELECT * FROM payments WHERE id=%s",(payment_id,))
            payment=await cur.fetchone()
            if approved and payment and cur.rowcount:
                await cur.execute("INSERT INTO purchases(user_id,content_id,payment_id) VALUES(%s,%s,%s) ON CONFLICT(user_id,content_id) DO NOTHING",
                                  (payment["user_id"],payment["content_id"],payment_id))
    return payment

async def get_user_ids(active_only=True):
    rows=await fetchall("SELECT telegram_id FROM users WHERE is_blocked=0" if active_only else "SELECT telegram_id FROM users")
    return [r["telegram_id"] for r in rows]

async def count(table,where=""):
    allowed={"users","contents","channels","payments","purchases"}
    if table not in allowed: raise ValueError("Invalid table")
    suffix=f" WHERE {where}" if where else ""
    row=await fetchone(f"SELECT COUNT(*) AS n FROM {table}{suffix}")
    return int(row["n"])

async def get_stats():
    return {"users":await count("users","is_blocked=0"),"contents":await count("contents","active=1"),
      "pending":await count("payments","status='pending'"),"approved":await count("payments","status='approved'"),
      "purchases":await count("purchases")}

async def save_broadcast(total,sent,failed,status="completed"):
    await execute("INSERT INTO broadcast_logs(total,sent,failed,status) VALUES(%s,%s,%s,%s)",(total,sent,failed,status))
async def set_setting(key,value):
    await execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",(key,value))
async def get_setting(key,default=""):
    row=await fetchone("SELECT value FROM settings WHERE key=%s",(key,))
    return row["value"] if row else default

async def export_backup():
    tables=("users","contents","channels","payment_methods","payments","purchases","settings","broadcast_logs")
    snapshot={}
    for table in tables:
        snapshot[table]=[dict(row) for row in await fetchall(f"SELECT * FROM {table}")]
    return json.dumps(snapshot,default=str,ensure_ascii=False,indent=2).encode("utf-8")
