import httpx
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from database.connection import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    update_user_webhook,
    regenerate_api_keys
)
from bot.keyboards import get_api_settings_keyboard
import config

WEBHOOK_URL_STATE = range(1)

async def api_settings_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if not user:
            return

    webhook_display = f"<code>{user.webhook_url}</code>" if user.webhook_url else "<i>تنظیم نشده</i>"

    msg = (
        "🔑 <b>تنظیمات وب‌سرویس و API بلوبات</b>\n\n"
        "از این اطلاعات می‌توانید برای اتصال فروشگاه ووکامرس یا اسکریپت‌های خود استفاده کنید:\n\n"
        f"🌐 <b>آدرس پایه API:</b>\n<code>{config.BASE_URL}/api/v1</code>\n\n"
        f"🟢 <b>کلید زنده (Live Key):</b>\n<code>{user.api_key_live}</code>\n\n"
        f"🟡 <b>کلید تست (Sandbox Key):</b>\n<code>{user.api_key_test}</code>\n\n"
        f"📡 <b>آدرس وب‌هوک جاری:</b>\n{webhook_display}\n\n"
        "💡 <i>راهنما: در هر درخواست cURL یا کتابخانه‌های زبان‌های مختلف، کلید را در هدر <code>X-API-Key</code> قرار دهید.</i>"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            parse_mode="HTML",
            reply_markup=get_api_settings_keyboard()
        )
    else:
        await update.message.reply_html(
            text=msg,
            reply_markup=get_api_settings_keyboard()
        )

async def start_set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🌐 لطفاً آدرس اینترنتی وب‌هوک سرور خود را ارسال فرمایید:\n"
        "(مثال: <code>https://myshop.com/api/blubot/webhook</code>)\n\n"
        "برای لغو /cancel را ارسال فرمایید.",
        parse_mode="HTML"
    )
    return WEBHOOK_URL_STATE

async def webhook_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_html("❌ آدرس وب‌هوک باید با http:// یا https:// آغاز شود:")
        return WEBHOOK_URL_STATE

    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if user:
            await update_user_webhook(db, user.id, url)

    await update.message.reply_html(
        f"✅ <b>آدرس وب‌هوک با موفقیت ثبت شد!</b>\n\n<code>{url}</code>\n\n"
        "از این پس هنگام تایید هر واریزی، اطلاعات تراکنش بلافاصله به این آدرس POST می‌شود."
    )
    return ConversationHandler.END

async def regen_keys_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("کلیدهای جدید صادر شد.")
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if user:
            live, test = await regenerate_api_keys(db, user.id)

    await query.message.reply_html(
        "🔄 <b>کلیدهای جدید با موفقیت صادر شدند:</b>\n\n"
        f"🟢 کلید زنده جدید:\n<code>{live}</code>\n\n"
        f"🟡 کلید تست جدید:\n<code>{test}</code>\n\n"
        "⚠️ توجه: کلیدهای قبلی منقضی شدند. لطفاً کلید جدید را در اسکریپت یا وب‌سایت خود جایگزین کنید."
    )

async def test_webhook_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال ارسال وب‌هوک تستی...")
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)

    if not user.webhook_url:
        await query.message.reply_html("❌ ابتدا باید یک آدرس وب‌هوک ثبت کنید.")
        return

    test_payload = {
        "success": True,
        "event": "payment.completed",
        "invoice_id": 9999,
        "status": "PAID",
        "amount": 1000000,
        "final_amount": 1000123,
        "mode": "test",
        "payer_name": "تست وب‌هوک",
        "payer_card": "6037991234567890",
        "payer_bank_name": "بانک ملی"
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(user.webhook_url, json=test_payload)
            status_code = res.status_code
            await query.message.reply_html(
                f"📡 <b>نتیجه ارسال وب‌هوک تستی:</b>\n\n"
                f"کد وضعیت دریافتی (HTTP Status): <b>{status_code}</b>\n"
                f"پاسخ سرور شما: <code>{res.text[:200]}</code>\n\n"
                + ("✅ وب‌هوک با موفقیت توسط سرور شما دریافت شد." if status_code == 200 else "⚠️ سرور شما پاسخی غیر از 200 ارسال کرد.")
            )
    except Exception as e:
        await query.message.reply_html(f"❌ خطا در برقراری ارتباط با سرور وب‌هوک: {e}")

def get_webhook_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_set_webhook, pattern="^set_webhook$")],
        states={
            WEBHOOK_URL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, webhook_url_received)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
