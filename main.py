import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config import BOT_TOKEN, OWNER_ID
from app.db import init_db
from app.handlers import router

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required on the bot worker.")
    if not OWNER_ID:
        raise RuntimeError("OWNER_ID must be your numeric Telegram user ID.")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    await init_db()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.set_my_commands([
      BotCommand(command="start",description="Open the content hub"),
      BotCommand(command="admin",description="Open owner admin panel"),
      BotCommand(command="cancel",description="Cancel current action")])
    try:
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__=="__main__":
    asyncio.run(main())
