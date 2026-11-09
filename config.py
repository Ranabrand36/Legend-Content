import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin").strip()
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "").strip()
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))
DB_PATH = os.getenv("DB_PATH", "data/legend_content_hub.sqlite3")
BOT_PUBLIC_URL = os.getenv("BOT_PUBLIC_URL", "").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
WELCOME_TEXT = os.getenv(
    "WELCOME_TEXT",
    "Welcome to <b>Legend Content Hub</b>! Choose an option below."
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing. Copy .env.example to .env and add your bot token.")
if not OWNER_ID_RAW.isdigit():
    raise RuntimeError("OWNER_ID must be your numeric Telegram user ID.")
if not WEB_PASSWORD:
    raise RuntimeError("WEB_PASSWORD is required. Set a strong password in .env.")

OWNER_ID = int(OWNER_ID_RAW)
