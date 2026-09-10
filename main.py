import asyncio
import logging
import uvicorn
import config
from database.connection import init_db
from core.poller import run_transaction_poller, set_poller_bot
from bot.bot_instance import create_bot_application
from api.app import app as fastapi_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("main")

async def main():
    logger.info("Initializing BluBot Platform...")

    # 1. Initialize SQLite / PostgreSQL database tables
    await init_db()
    logger.info("Database initialized successfully.")

    # 2. Setup Telegram Bot
    bot_app = create_bot_application()
    if bot_app:
        set_poller_bot(bot_app.bot)
        await bot_app.initialize()
        await bot_app.start()
        if bot_app.updater:
            await bot_app.updater.start_polling()

        # Discover Bot Username and Configure Telegram Menu Button for Mini App
        try:
            me = await bot_app.bot.get_me()
            if me and me.username:
                config.BOT_USERNAME = me.username
                logger.info(f"Bot connected successfully as: @{config.BOT_USERNAME}")

            # Register standard bot commands in Telegram UI
            try:
                from telegram import BotCommand
                await bot_app.bot.set_my_commands([
                    BotCommand("start", "شروع و منوی اصلی"),
                    BotCommand("miniapp", "📱 ورود به مینی‌اپ بلوبات"),
                    BotCommand("help", "📖 راهنما و مستندات")
                ])
            except Exception as e:
                logger.warning(f"Could not register bot commands: {e}")

            if config.BASE_URL.startswith("https://"):
                from telegram import MenuButtonWebApp, WebAppInfo
                await bot_app.bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="📱 مینی‌اپ",
                        web_app=WebAppInfo(url=f"{config.BASE_URL}/miniapp")
                    )
                )
                logger.info(f"Telegram Chat Menu Button set to Mini App ({config.BASE_URL}/miniapp).")
            else:
                logger.info(
                    f"BASE_URL is '{config.BASE_URL}'. Note: Telegram Mini Apps require HTTPS (e.g. cloudflare tunnel or domain with SSL) to open in-app. In HTTP mode, link opens in browser."
                )
        except Exception as e:
            logger.warning(f"Could not configure Chat Menu Button: {e}")

        logger.info("Telegram Bot started successfully.")
    else:
        logger.warning("Telegram Bot skipped (No BOT_TOKEN configured in .env).")

    # 3. Launch background transaction poller
    poller_task = asyncio.create_task(run_transaction_poller())

    # 4. Launch FastAPI REST server with Uvicorn
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(uvicorn_config)
    logger.info(f"API Server listening at http://{config.SERVER_HOST}:{config.SERVER_PORT}")

    try:
        await server.serve()
    finally:
        poller_task.cancel()
        if bot_app and bot_app.updater:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        logger.info("BluBot Platform shut down gracefully.")

if __name__ == "__main__":
    asyncio.run(main())
