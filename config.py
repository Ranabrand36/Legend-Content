import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
OWNER_ID_RAW=os.getenv("OWNER_ID","").strip()
WEB_USERNAME=os.getenv("WEB_USERNAME","admin").strip()
WEB_PASSWORD=os.getenv("WEB_PASSWORD","").strip()
WEB_HOST=os.getenv("WEB_HOST","0.0.0.0")
WEB_PORT=int(os.getenv("PORT",os.getenv("WEB_PORT","8000")))
DATABASE_URL=os.getenv("DATABASE_URL","").strip()
BOT_PUBLIC_URL=os.getenv("BOT_PUBLIC_URL","").strip()
SUPPORT_USERNAME=os.getenv("SUPPORT_USERNAME","").strip()
WELCOME_TEXT=os.getenv("WELCOME_TEXT","Welcome to <b>Legend Content Hub</b>! Choose an option below.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add your Supabase PostgreSQL connection string.")
if OWNER_ID_RAW and not OWNER_ID_RAW.isdigit():
    raise RuntimeError("OWNER_ID must be a numeric Telegram user ID.")
OWNER_ID=int(OWNER_ID_RAW) if OWNER_ID_RAW.isdigit() else 0
