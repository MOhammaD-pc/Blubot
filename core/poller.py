import asyncio
import logging
from typing import Optional
from database.connection import AsyncSessionLocal
from database.crud import get_all_active_sessions
from database.models import User
from blubank.session_manager import SessionManager
from core.matching_engine import MatchingEngine
import config

logger = logging.getLogger("poller")

# Reference to telegram bot instance for sending alerts
_bot_instance = None

def set_poller_bot(bot):
    global _bot_instance
    _bot_instance = bot

async def run_transaction_poller():
    """
    Background worker that continuously polls active BluBank sessions,
    matches deposits with pending invoices, and notifies merchants via Telegram.
    """
    logger.info("Starting BluBank transaction poller worker...")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # 1. Clean expired invoices
                await MatchingEngine.clean_expired(db)

                # 2. Fetch active sessions
                sessions = await get_all_active_sessions(db)
                for session in sessions:
                    try:
                        client = SessionManager.get_client(session)
                        transactions = await client.fetch_statement(limit=15)

                        for tx in transactions:
                            if not tx.is_deposit:
                                continue

                            result = await MatchingEngine.match_and_process_deposit(
                                db=db,
                                card_number=session.card_number,
                                tx=tx
                            )

                            if result:
                                invoice, fee_charged, is_low_balance = result
                                user = await db.get(User, invoice.user_id)
                                if user and _bot_instance:
                                    await _notify_merchant_telegram(user, invoice, fee_charged, is_low_balance)

                    except Exception as sess_err:
                        logger.debug(f"Error polling session {session.id}: {sess_err}")
                        if "401" in str(sess_err) or "Unauthorized" in str(sess_err):
                            session.status = "EXPIRED"
                            await db.commit()
                            user = await db.get(User, session.user_id)
                            if user and _bot_instance:
                                await _notify_session_expired(user, session)

        except Exception as e:
            logger.error(f"Poller loop iteration error: {e}")

        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

async def _notify_session_expired(user: User, session):
    """Sends real-time notification to merchant when bank session expires."""
    try:
        if not _bot_instance:
            return
        card_fmt = " ".join([session.card_number[i:i+4] for i in range(0, len(session.card_number), 4)])
        msg = (
            "⚠️ <b>هشدار مهم: نشست بلوبانک شما نیاز به ورود مجدد دارد!</b>\n\n"
            f"💳 <b>شماره کارت:</b> <code>{card_fmt}</code>\n"
            "🔴 <b>وضعیت:</b> نشست در بلوبانک منقضی گردید یا از داخل همراه بانک خارج شدید.\n\n"
            "جهت تداوم تایید خودکار واریزی‌ها و دریافت وب‌هوک، لطفاً وارد <b>مینی‌اپ بلوبات</b> شده و نشست خود را مجدداً متصل فرمایید."
        )
        await _bot_instance.send_message(
            chat_id=user.telegram_id,
            text=msg,
            parse_mode="HTML"
        )
    except Exception as err:
        logger.error(f"Failed to send expiration alert to user {user.telegram_id}: {err}")

async def _notify_merchant_telegram(user: User, invoice, fee_charged: int, is_low_balance: bool):
    """Sends real-time Telegram receipt and notification to the merchant."""
    try:
        toman_amount = invoice.base_amount // 10
        toman_final = invoice.final_amount // 10
        toman_fee = fee_charged // 10
        toman_wallet = user.wallet_balance // 10

        msg = (
            "🔔 <b>واریز جدید با موفقیت تأیید شد!</b>\n\n"
            f"🧾 <b>شماره فاکتور:</b> <code>#{invoice.id}</code>\n"
            f"💳 <b>کارت مقصد:</b> <code>{invoice.card_number}</code>\n"
            f"💰 <b>مبلغ فاکتور:</b> {toman_amount:,} تومان\n"
            f"🔢 <b>مبلغ دریافتی دقیق:</b> {toman_final:,} تومان\n"
            f"👤 <b>واریزکننده:</b> {invoice.payer_name or 'نامشخص'}\n"
            f"💳 <b>کارت مبدأ:</b> <code>{invoice.payer_card or 'نامشخص'}</code>\n"
            f"🏦 <b>بانک مبدأ:</b> {invoice.payer_bank_name or 'شتاب'}\n"
            f"🔖 <b>کد رهگیری:</b> <code>{invoice.bank_track_id or 'ثبت شد'}</code>\n"
            "──────────────\n"
            f"📉 <b>کارمزد کسر شده:</b> {toman_fee:,} تومان\n"
            f"👛 <b>مانده کیف پول شما:</b> {toman_wallet:,} تومان\n"
        )

        if is_low_balance:
            msg += "\n⚠️ <b>هشدار موجودی:</b> اعتبار کیف پول شما رو به اتمام است. لطفاً جهت جلوگیری از توقف فاکتورها، حساب خود را شارژ کنید."

        await _bot_instance.send_message(
            chat_id=user.telegram_id,
            text=msg,
            parse_mode="HTML"
        )
    except Exception as err:
        logger.error(f"Failed to send Telegram notification to user {user.telegram_id}: {err}")
