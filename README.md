# 👑 Legend Content Hub

Telegram content-delivery bot with paid/free access, manual payment approval, owner controls and a read-only web dashboard.

## Deployment architecture

- **Telegram bot:** persistent Python worker (polling; do not deploy as a Vercel function).
- **Dashboard:** FastAPI app deployed separately to Vercel using `api/index.py`.
- **Database:** shared Supabase PostgreSQL database. Both services use the same `DATABASE_URL`.
- **Admin access:** one Telegram owner ID; dashboard protected by HTTP Basic Authentication.

## Features

- Single-owner Telegram admin panel.
- User registration, content browsing and purchase history.
- Force-join multiple channels with membership verification.
- Upload text, links, photos, videos, documents, audio, voice, animation and video notes.
- Free and PKR-priced content with unique deep links.
- Edit, activate/deactivate and delete content.
- Manual payment methods and proof/reference submission.
- Owner approval/rejection and automatic delivery after approval.
- Broadcast with confirmation and delivery counts.
- PostgreSQL-backed users, content, channels, payments, purchases, settings and broadcast logs.
- Authenticated, read-only dashboard with stats and recent payment requests.
- Owner-triggered JSON data export backup from PostgreSQL.

## 1. Supabase setup

1. Create a Supabase project.
2. Open **Connect** and copy the **Transaction Pooler** PostgreSQL connection string.
3. Keep the password private. Do not commit it to GitHub.
4. The app creates its tables automatically on first startup. Do not manually create the schema.

Use the full connection string as `DATABASE_URL`, including SSL mode. Example format only:

```text
postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres?sslmode=require
```

Replace every placeholder with the values Supabase gives your project. If the password contains URL-reserved characters, use the URL-encoded password from the connection string.

## 2. Telegram worker deployment

Deploy the repository to an always-on Python worker host. Set these environment variables in the host's private environment settings:

- `BOT_TOKEN` — token from BotFather.
- `OWNER_ID` — your numeric Telegram user ID.
- `DATABASE_URL` — Supabase Transaction Pooler connection string.
- `WEB_USERNAME` — dashboard login username.
- `WEB_PASSWORD` — long, unique dashboard password.
- `BOT_PUBLIC_URL` — optional Vercel dashboard URL.
- `SUPPORT_USERNAME` — optional support username.

Build/install command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
python main.py
```

The worker must remain running continuously. Do not run two polling workers with the same bot token.

## 3. Vercel dashboard deployment

1. Import this GitHub repository into Vercel.
2. Set the same `DATABASE_URL` in Vercel Project → Settings → Environment Variables.
3. Also set `WEB_USERNAME` and a strong `WEB_PASSWORD`.
4. Deploy. Vercel serves the FastAPI dashboard from `api/index.py`.
5. Open the deployed URL and sign in using the dashboard credentials.

The dashboard is intentionally read-only. Uploads, channel rules, payment methods, payment reviews and broadcasts remain in the Telegram owner panel.

## 4. Local development

Python 3.10+ is required.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Set real values in `.env` before starting.

## Backups and data migration

The Telegram backup action exports all application tables to a JSON file. Store exports securely; they contain user IDs and payment references. This export is a data snapshot, not a complete PostgreSQL schema/roles backup.

The PostgreSQL migration creates a new empty schema. Existing SQLite data is **not** automatically imported. If the old SQLite database contains real users, content or payment history, migrate it separately before switching the live bot.

## Important operational notes

- Add the bot as an administrator in force-join channels so membership checks work.
- Manually verify wallet transactions in your payment account before approving.
- Telegram `protect_content` is a deterrent, not guaranteed DRM.
- FSM uses in-memory storage; an in-progress multi-step wizard is cleared if the worker restarts.
- Supabase free projects may pause under provider inactivity policies. A persistent worker does not prevent database pausing.
- Never commit `.env`, tokens, passwords, connection strings or private payment/user data.
