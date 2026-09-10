import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
import config
from bot.handlers.start import start_handler, help_handler, miniapp_menu_handler
from bot.handlers.bank import (
    bank_menu_handler,
    get_connect_conversation_handler,
    refresh_session_handler,
    disconnect_session_handler
)
from bot.handlers.wallet import (
    wallet_menu_handler,
    wallet_history_handler,
    start_topup,
    preset_topup_handler,
    get_topup_conversation_handler
)
from bot.handlers.invoices import (
    get_invoice_conversation_handler,
    list_transactions_handler
)
from bot.handlers.api_settings import (
    api_settings_menu_handler,
    get_webhook_conversation_handler,
    regen_keys_handler,
    test_webhook_handler
)
from bot.handlers.admin import (
    admin_panel_handler,
    admin_stats_handler,
    admin_users_handler
)

logger = logging.getLogger("bot")

def create_bot_application() -> Application:
    if not config.BOT_TOKEN:
        logger.warning("BOT_TOKEN is not set in environment. Telegram bot will run in standby mode.")
        return None

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler(["miniapp", "app", "panel"], miniapp_menu_handler))

    # Conversation Handlers
    app.add_handler(get_connect_conversation_handler())
    app.add_handler(get_topup_conversation_handler())
    app.add_handler(get_invoice_conversation_handler())
    app.add_handler(get_webhook_conversation_handler())

    # Main Menu Reply Keyboard Handlers
    app.add_handler(MessageHandler(filters.Regex("^📱 مینی‌اپ"), miniapp_menu_handler))
    app.add_handler(MessageHandler(filters.Regex("^💳 حساب‌ها و نشست‌ها$"), bank_menu_handler))
    app.add_handler(MessageHandler(filters.Regex("^👛 کیف پول و اعتبار$"), wallet_menu_handler))
    app.add_handler(MessageHandler(filters.Regex("^📊 گزارش تراکنش‌ها$"), list_transactions_handler))
    app.add_handler(MessageHandler(filters.Regex("^🔑 تنظیمات API و وب‌هوک$"), api_settings_menu_handler))
    app.add_handler(MessageHandler(filters.Regex("^🛠 راهنما و مستندات$"), help_handler))
    app.add_handler(MessageHandler(filters.Regex("^👑 پنل مدیریت پلتفرم$"), admin_panel_handler))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(refresh_session_handler, pattern="^bank_refresh$"))
    app.add_handler(CallbackQueryHandler(disconnect_session_handler, pattern="^bank_disconnect$"))
    app.add_handler(CallbackQueryHandler(bank_menu_handler, pattern="^bank_menu$"))

    app.add_handler(CallbackQueryHandler(start_topup, pattern="^wallet_topup$"))
    app.add_handler(CallbackQueryHandler(wallet_history_handler, pattern="^wallet_history$"))
    app.add_handler(CallbackQueryHandler(preset_topup_handler, pattern="^topup_"))

    app.add_handler(CallbackQueryHandler(regen_keys_handler, pattern="^regen_api_keys$"))
    app.add_handler(CallbackQueryHandler(test_webhook_handler, pattern="^test_webhook$"))

    app.add_handler(CallbackQueryHandler(admin_stats_handler, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users_handler, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_panel_handler, pattern="^admin_panel$"))

    return app
