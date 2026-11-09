# 👑 Legend Content Hub — Full Project

Complete Telegram content delivery + paid/free access bot with a read-only web monitoring dashboard.

## Features included

- Single-owner admin access (`OWNER_ID`); no sub-admin accounts.
- User registration and main menu.
- Force-join multiple public/private channels.
- Re-check membership before browsing and receiving content.
- Content upload from Telegram: text, links, photos, videos, documents, audio, voice, animation and video notes.
- Free or PKR-priced content.
- Unique deep links for every content item.
- Content listing, title/description editing, activation/deactivation, price changes and deletion.
- Manual payment methods (JazzCash, Easypaisa or other account details).
- Users submit transaction reference and optional screenshot/document proof.
- Owner approves/rejects payment requests from Telegram.
- Approved access is recorded and content is delivered automatically.
- Broadcast text/media/forwarded messages to registered users, with confirmation and result counts.
- Basic statistics and recent payment monitoring in a password-protected web dashboard.
- Owner-triggered SQLite database backup sent to the Telegram owner chat.
- SQLite database created automatically.

## Requirements

- Python 3.10+
- A Telegram bot token from `@BotFather`
- Your numeric Telegram user ID
- For force join: add the bot as an administrator in every required channel.
- Open the bot in your owner Telegram account and send `/start` once so it can send you payment alerts and database backups.
- For public web access: deploy behind HTTPS/reverse proxy. The dashboard uses HTTP Basic Authentication.

## Installation (Windows)

1. Extract the ZIP.
2. Open PowerShell in the extracted folder.
3. Create a virtual environment:

   `py -m venv .venv`

4. Activate it:

   `.venv\\Scripts\\Activate.ps1`

5. Install dependencies:

   `pip install -r requirements.txt`

6. Copy `.env.example` to `.env` (Windows PowerShell: `Copy-Item .env.example .env`).
7. Edit `.env` and set:
   - `BOT_TOKEN`
   - `OWNER_ID`
   - `WEB_PASSWORD` (use a long unique password)
8. Start:

   `python main.py`

## Installation (Linux / VPS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

Use a process manager such as systemd or Supervisor to keep the app running after logout/reboot. Do not run multiple polling instances using the same bot token.

## Telegram usage

- Send `/start` to the bot as a user.
- Send `/admin` from the owner account to open the owner panel.
- Add content from the panel. The wizard asks for title, description, price (`free` or a PKR amount), then the content message.
- Generate a unique link from Manage Content → item → Get Link.
- Manage force join channels from Force Join. Format: `@channelusername | https://t.me/channelusername`
- Add a payment method from Payment Details. Supply name, account holder, account number and instructions.
- Broadcast from the panel. Send a message/media, review target count, then confirm.
- Approve/reject payments using the inline buttons sent to the owner.

## Web dashboard

The FastAPI dashboard starts with the bot on port `8000` by default.
Open `http://YOUR_SERVER_IP:8000/` and enter `WEB_USERNAME` / `WEB_PASSWORD`.

For public production use, put it behind HTTPS (for example, Nginx + a TLS certificate). Do not expose the dashboard over plain HTTP on an untrusted network. Set `BOT_PUBLIC_URL` to the HTTPS address to show it in the Telegram panel.

The web dashboard is intentionally read-only. Content, force-join channels, payment details, payment reviews and broadcasts are managed from the Telegram owner panel, as requested.

## Important operation notes

- The bot must be an administrator in force-join channels so Telegram can verify membership of other users.
- Private channel invite links can be used for the join buttons. The bot must be added to the channel first.
- Payment screenshots are only evidence submitted by the buyer. Owner must independently verify the transaction in the wallet/account before approving.
- `protect_content` asks Telegram to restrict forwarding/saving, but it is not absolute DRM or a guarantee against copying.
- SQLite is suitable for a small/medium initial deployment. For high traffic or multiple app instances, migrate to PostgreSQL and use a persistent shared FSM storage (such as Redis).
- Back up `data/legend_content_hub.sqlite3` regularly. You can also use the Database Backup button in `/admin`; restore a backup only after stopping the bot.
- Never share `.env`, bot token, or dashboard password. Do not commit them to GitHub.

## Known scope / future upgrades

- Broadcast is sequential and reports success/failure. It uses a small delay to reduce rate-limit risk.
- FSM state uses in-memory storage and is cleared if the process restarts mid-wizard.
- No automatic wallet API payment integration is included; payment verification is manual, by design.
- No public user registration or web-based content editing is enabled.
