import secrets
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from config import WEB_USERNAME, WEB_PASSWORD
from app.db import get_stats, fetchall

app = FastAPI(title="Legend Content Hub Dashboard", docs_url=None, redoc_url=None)
security = HTTPBasic()

def auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, WEB_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, WEB_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Invalid credentials",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(_: str = Depends(auth)):
    stats = await get_stats()
    recent = await fetchall("""
        SELECT p.order_code,p.status,p.transaction_ref,u.first_name,c.title,p.created_at
        FROM payments p
        LEFT JOIN users u ON u.telegram_id=p.user_id
        LEFT JOIN contents c ON c.id=p.content_id
        ORDER BY p.id DESC LIMIT 12
    """)
    cards = "".join(
        f"<div class='card'><small>{label}</small><strong>{value}</strong></div>"
        for label, value in [
            ("Active users", stats["users"]), ("Active content", stats["contents"]),
            ("Pending payments", stats["pending"]), ("Approved payments", stats["approved"]),
            ("Purchases", stats["purchases"])
        ]
    )
    trs = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            r["order_code"], r["first_name"] or "Unknown", r["title"] or "Deleted",
            r["status"], r["created_at"]
        ) for r in recent
    ) or "<tr><td colspan='5'>No payment records yet.</td></tr>"
    return f"""<!doctype html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Legend Content Hub</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#08110f;color:#e8f2ed;font:15px Arial,sans-serif}}
    .wrap{{max-width:1100px;margin:auto;padding:28px 18px}}.top{{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}}
    h1{{margin:0;color:#8df0bd}}.muted{{color:#9cb4a8}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:24px 0}}
    .card,section{{background:#10201b;border:1px solid #244438;border-radius:14px;padding:18px}}
    .card small{{display:block;color:#9cb4a8;margin-bottom:10px}}.card strong{{font-size:30px}}
    table{{width:100%;border-collapse:collapse;margin-top:12px;min-width:650px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #244438}}
    th{{color:#8df0bd}}.tablewrap{{overflow-x:auto}}.note{{margin-top:18px;color:#9cb4a8;font-size:13px}}
    </style></head><body><div class="wrap"><div class="top"><div><h1>👑 Legend Content Hub</h1>
    <p class="muted">Owner monitoring dashboard · Read-only</p></div><span class="muted">Single Owner Mode</span></div>
    <div class="grid">{cards}</div><section><h2>Recent payment requests</h2><div class="tablewrap">
    <table><thead><tr><th>Order</th><th>User</th><th>Content</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>{trs}</tbody></table></div></section>
    <p class="note">Content uploads, force-join settings, payment method changes and broadcasts are controlled from the Telegram owner panel.</p>
    </div></body></html>"""
