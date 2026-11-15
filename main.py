import asyncio
import signal

from loguru import logger

logger.add(
    "data/bot.log",
    rotation="10 MB",
    retention=3,
    format="{time} | {level} | {module}:{function}:{line} | {message}",
)


async def main() -> None:
    from aiogram import Bot, Dispatcher
    from config.settings import settings
    from src.db.database import init_db
    from src.bot.handlers.admin import router as admin_router
    from src.bot.handlers.owner import router as owner_router
    from src.bot.handlers.payment import router as payment_router
    from src.bot.handlers.client import router as client_router
    from src.bot.middlewares import InjectBusinessMiddleware
    from src.scheduler.jobs import setup_scheduler

    logger.info("Starting Replly Bot...")

    await init_db()
    logger.info("Database initialized")

    bot = Bot(token=settings.BOT_TOKEN)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")

    dp = Dispatcher()
    dp.message.middleware(InjectBusinessMiddleware())
    dp.callback_query.middleware(InjectBusinessMiddleware())

    dp.include_routers(admin_router, owner_router, payment_router, client_router)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(dp, bot, scheduler)))

    logger.info("Bot is starting polling...")
    await dp.start_polling(bot)


async def shutdown(dp, bot, scheduler) -> None:
    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
