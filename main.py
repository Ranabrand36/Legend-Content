import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config import BOT_TOKEN, WEB_HOST, WEB_PORT
from app.db import init_db
from app.handlers import router
from app.web import app as web_app

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Open the content hub"),
        BotCommand(command="admin", description="Open owner admin panel"),
        BotCommand(command="cancel", description="Cancel current admin/user action"),
    ])

    config = uvicorn.Config(web_app, host=WEB_HOST, port=WEB_PORT, log_level="info")
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            server.serve()
        )
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
