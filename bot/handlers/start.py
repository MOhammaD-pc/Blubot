import datetime
from telegram import Update
from telegram.ext import ContextTypes
from database.connection import AsyncSessionLocal
from database.crud import get_or_create_user
from bot.keyboards import get_main_keyboard, get_miniapp_inline_keyboard
import config

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    if not user_tg:
        return

    is_admin = (user_tg.id == config.ADMIN_TELEGRAM_ID)

    async with AsyncSessionLocal() as db:
        user, is_new = await get_or_create_user(
            db=db,
            telegram_id=user_tg.id,
            username=user_tg.username,
            first_name=user_tg.first_name
        )

    toman_balance = user.wallet_balance // 10
    welcome_msg = (
        f"سلام <b>{user_tg.first_name}</b> عزیز! 👋\n"
        "به ربات درگاه هوشمند کارت‌به‌کارت <b>بلوبات (BluBot)</b> خوش آمدید.\n\n"
        "🚀 <b>مزایای این سیستم:</b>\n"
        "• اتصال مستقیم به بلوبانک از طریق <b>نشست فعال (Active Session)</b>\n"
        "• عدم وابستگی به گوشی موبایل یا فورواردر پیامک (SMS Forwarder)\n"
        "• تشخیص آنی واریزی با تطبیق دقیق مبلغ و ثبت لحظه‌ای\n"
        "• دریافت آنی نام واریزکننده، شماره کارت و کد رهگیری\n"
        "• وب‌سرویس REST و وب‌هوک برای اتصال به سایت و فروشگاه‌ها\n\n"
    )

    if is_new:
        welcome_msg += "🎁 <b>هدیه عضویت:</b> ماه اول استفاده برای شما <b>کاملاً رایگان (کارمزد ۰)</b> فعال گردید!\n\n"

    welcome_msg += (
        f"👛 <b>موجودی کیف پول:</b> {toman_balance:,} تومان\n"
        f"⚙️ <b>تعرفه کارمزد شما:</b> {user.fee_percent}% (تا سقف {user.fee_cap // 10:,} تومان)\n\n"
        "از منوی زیر بخش مورد نظر خود را انتخاب فرمایید:"
    )

    # Ensure Menu Button is set for this user
    try:
        miniapp_url = f"{config.BASE_URL}/miniapp"
        if miniapp_url.startswith("https://"):
            from telegram import MenuButtonWebApp, WebAppInfo
            await context.bot.set_chat_menu_button(
                chat_id=user_tg.id,
                menu_button=MenuButtonWebApp(
                    text="📱 مینی‌اپ",
                    web_app=WebAppInfo(url=miniapp_url)
                )
            )
    except Exception:
        pass

    await update.message.reply_html(
        text=welcome_msg,
        reply_markup=get_main_keyboard(is_admin)
    )

    # Send Mini App inline button for instant access
    await update.message.reply_html(
        text="👇 <b>ورود به مینی‌اپ بلوبات (ثبت‌نام / مشاهده کلیدها / تنظیمات):</b>",
        reply_markup=get_miniapp_inline_keyboard()
    )

async def miniapp_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback handler when user clicks the miniapp keyboard button in HTTP mode or runs /miniapp"""
    user_tg = update.effective_user
    is_admin = (user_tg.id == config.ADMIN_TELEGRAM_ID) if user_tg else False

    try:
        miniapp_url = f"{config.BASE_URL}/miniapp"
        if miniapp_url.startswith("https://") and user_tg:
            from telegram import MenuButtonWebApp, WebAppInfo
            await context.bot.set_chat_menu_button(
                chat_id=user_tg.id,
                menu_button=MenuButtonWebApp(
                    text="📱 مینی‌اپ",
                    web_app=WebAppInfo(url=miniapp_url)
                )
            )
    except Exception:
        pass

    miniapp_url = f"{config.BASE_URL}/miniapp"
    if miniapp_url.startswith("https://"):
        msg = (
            "📱 <b>مینی‌اپ بلوبات:</b>\n\n"
            "روی دکمه شیشه‌ای زیر کلیک کنید تا مینی‌اپ باز شود:"
        )
    else:
        msg = (
            "📱 <b>مینی‌اپ بلوبات:</b>\n\n"
            "⚠️ برای باز شدن مستقیم مینی‌اپ درون تلگرام، آدرس دامنه باید دارای گواهی SSL (با پروتکل <b>https://</b>) باشد.\n"
            f"آدرس فعلی سرور: <code>{config.BASE_URL}</code>\n\n"
            "🌐 برای باز کردن پنل در مرورگر، روی دکمه زیر کلیک کنید:"
        )
    await update.message.reply_html(
        text=msg,
        reply_markup=get_miniapp_inline_keyboard()
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    is_admin = (user_tg.id == config.ADMIN_TELEGRAM_ID) if user_tg else False

    msg = (
        "📖 <b>راهنمای کار با سیستم بلوبات:</b>\n\n"
        "۱. <b>اتصال حساب:</b> از دکمه <i>حساب‌ها و نشست‌ها</i> شماره متصل به بلوبانک خود را وارد کنید تا نشست فعال ثبت شود.\n\n"
        "۲. <b>صدور فاکتور:</b> می‌توانید از دکمه <i>صدور فاکتور سریع</i> در ربات یا از طریق <i>API</i> برای فروشگاه خود فاکتور بسازید.\n\n"
        "۳. <b>تطبیق خودکار:</b> سیستم برای هر فاکتور چند تومان آفست تصادفی اضافه می‌کند. به محض واریز دقیق مبلغ توسط مشتری، فاکتور تأیید و وب‌هوک ارسال می‌شود.\n\n"
        "۴. <b>کیف پول و کارمزد:</b> چون پول مستقیماً به حساب شما می‌آید، کارمزد تراکنش‌ها به صورت خودکار از موجودی کیف پول اعتباری شما در ربات کسر می‌گردد."
    )
    await update.message.reply_html(
        text=msg,
        reply_markup=get_main_keyboard(is_admin)
    )
