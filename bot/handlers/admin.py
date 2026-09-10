from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func
from database.connection import AsyncSessionLocal
from database.models import User, BankSession, Invoice, WalletLedger
from bot.keyboards import get_admin_keyboard
import config

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    if user_tg.id != config.ADMIN_TELEGRAM_ID:
        await update.message.reply_html("⛔️ شما به این بخش دسترسی ندارید.")
        return

    msg = (
        "👑 <b>پنل مدیریت کل پلتفرم بلوبات</b>\n\n"
        "مدیر گرامی، به پنل کنترل پلتفرم خوش آمدید.\n"
        "از دکمه‌های زیر برای بررسی آمار کلی مالی، سود حاصل از کارمزدها و مدیریت سیستم استفاده نمایید:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    else:
        await update.message.reply_html(
            text=msg,
            reply_markup=get_admin_keyboard()
        )

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != config.ADMIN_TELEGRAM_ID:
        return

    async with AsyncSessionLocal() as db:
        # Total users
        res_users = await db.execute(select(func.count(User.id)))
        total_users = res_users.scalar() or 0

        # Total active sessions
        res_sessions = await db.execute(select(func.count(BankSession.id)).where(BankSession.status == "ACTIVE"))
        active_sessions = res_sessions.scalar() or 0

        # Total volume processed
        res_vol = await db.execute(select(func.sum(Invoice.final_amount)).where(Invoice.status == "PAID"))
        total_volume_rials = res_vol.scalar() or 0

        # Total fees earned (sum of COMMISSION in wallet_ledger)
        res_fees = await db.execute(
            select(func.sum(WalletLedger.amount)).where(WalletLedger.type == "COMMISSION")
        )
        total_fees_rials = abs(res_fees.scalar() or 0)

        # Paid invoices count
        res_paid_count = await db.execute(select(func.count(Invoice.id)).where(Invoice.status == "PAID"))
        paid_count = res_paid_count.scalar() or 0

    toman_vol = total_volume_rials // 10
    toman_fees = total_fees_rials // 10

    stats_msg = (
        "📊 <b>گزارش جامع آماری پلتفرم بلوبات:</b>\n\n"
        f"👥 <b>تعداد کل کاربران ثبت‌نامی:</b> {total_users:,} کاربر\n"
        f"💳 <b>نشست‌های فعال بلوبانک:</b> {active_sessions:,} نشست\n"
        f"🧾 <b>تعداد تراکنش‌های موفق:</b> {paid_count:,} تراکنش\n"
        f"💰 <b>مجموع گردش مالی عبوری:</b> {toman_vol:,} تومان\n"
        "───────────────\n"
        f"💎 <b>کل درآمد کارمزد پلتفرم:</b> <b>{toman_fees:,} تومان</b>\n\n"
        f"⚙️ <b>نرخ کارمزد پیش‌فرض سیستم:</b> {config.DEFAULT_FEE_PERCENT}%\n"
        f"🛡 <b>سقف کارمزد پیش‌فرض:</b> {config.DEFAULT_FEE_CAP // 10:,} تومان"
    )

    await query.message.reply_html(stats_msg)

async def admin_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != config.ADMIN_TELEGRAM_ID:
        return

    async with AsyncSessionLocal() as db:
        stmt = select(User).order_by(User.id.desc()).limit(10)
        res = await db.execute(stmt)
        users = res.scalars().all()

    lines = ["👥 <b>آخرین کاربران ثبت نام شده:</b>\n"]
    for u in users:
        toman_bal = u.wallet_balance // 10
        username = f"@{u.username}" if u.username else u.first_name
        lines.append(f"• ID: <code>{u.telegram_id}</code> ({username}) | مانده: {toman_bal:,} ت | کارمزد: {u.fee_percent}%")

    await query.message.reply_html("\n".join(lines))
