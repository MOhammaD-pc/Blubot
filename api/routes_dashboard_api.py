import datetime
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.connection import get_db
from database.models import User, BankSession
from database.crud import (
    get_or_create_user,
    get_user_by_telegram_id,
    get_user_by_api_key,
    update_user_webhook,
    regenerate_api_keys,
    create_invoice,
    get_user_sessions,
    get_user_invoices,
    modify_wallet_balance,
    save_bank_session,
    delete_session
)
from core.matching_engine import MatchingEngine
from core.telegram_auth import validate_telegram_init_data, create_magic_link_token
from api.routes_web import get_session_user_id
from blubank.client import BluBankClient
from blubank.crypto import encrypt_session_data
from blubank.session_manager import SessionManager
import core.poller as poller_module

router = APIRouter(prefix="/api/v1", tags=["Dashboard AJAX"])

class LoginRequest(BaseModel):
    identifier: str | None = None
    api_key: str | None = None

class MiniAppAuthRequest(BaseModel):
    init_data: str

class WebhookRequest(BaseModel):
    webhook_url: str

class QuickInvoiceRequest(BaseModel):
    amount: int

class TopupRequest(BaseModel):
    amount: int

class FeeUpdateRequest(BaseModel):
    fee_percent: float
    fee_cap: int

class BankOtpRequest(BaseModel):
    phone_number: str
    username: str | None = None
    password: str | None = None

class BankVerifyRequest(BaseModel):
    phone_number: str
    otp: str
    temp_token: str | None = None

@router.post("/auth/login")
async def web_login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Website login: only for ALREADY REGISTERED users.
    Registration from website is intentionally blocked (BluPal style).
    New users must register via Telegram / MiniApp.
    """
    user = None

    # Try API Key authentication if provided
    if payload.api_key and payload.api_key.strip():
        auth = await get_user_by_api_key(db, payload.api_key.strip())
        if auth:
            user = auth[0]

    # Try Identifier (Telegram ID) ONLY for existing users
    if not user and payload.identifier and payload.identifier.strip():
        clean_id = "".join([c for c in payload.identifier if c.isdigit()])
        if clean_id:
            tg_id = int(clean_id)
            user = await get_user_by_telegram_id(db, telegram_id=tg_id)

    if not user:
        return JSONResponse({
            "success": False,
            "message": "حساب کاربری با این مشخصات یافت نشد! ثبت‌نام در بلوبات فقط از طریق ربات و مینی‌اپ تلگرام انجام می‌شود."
        }, status_code=404)

    res = JSONResponse({"success": True, "user_id": user.id})
    res.set_cookie(
        key="blupal_user_id",
        value=str(user.id),
        httponly=True,
        max_age=86400 * 30,  # 30 days
        samesite="lax"
    )
    return res

@router.post("/auth/miniapp")
async def miniapp_auth(payload: MiniAppAuthRequest, db: AsyncSession = Depends(get_db)):
    """
    Telegram Mini App authentication endpoint:
    Verifies Telegram initData HMAC signature.
    If user is new, automatically registers them with 1 month free trial.
    If user exists, logs them in and updates their info.
    """
    init_data = payload.init_data.strip() if payload.init_data else ""
    if not init_data:
        return JSONResponse({"success": False, "message": "داده‌های تلگرام ارسال نشده است."}, status_code=400)

    # Validate initData with Bot Token
    is_valid, tg_user = validate_telegram_init_data(init_data, config.BOT_TOKEN)

    # In local development if BOT_TOKEN is empty, allow mock for testing
    if not is_valid and (not config.BOT_TOKEN or config.BOT_TOKEN == "your_telegram_bot_token_here"):
        # For offline dev testing only if token not configured
        import urllib.parse, json
        try:
            parsed = dict(urllib.parse.parse_qsl(init_data))
            if "user" in parsed:
                tg_user = json.loads(parsed["user"])
                is_valid = True
        except Exception:
            pass

    if not is_valid or not tg_user or "id" not in tg_user:
        return JSONResponse({"success": False, "message": "امضای داده‌های تلگرام نامعتبر است."}, status_code=401)

    tg_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or "پذیرنده"

    user, is_new = await get_or_create_user(
        db=db,
        telegram_id=tg_id,
        username=username,
        first_name=first_name
    )

    res = JSONResponse({
        "success": True,
        "is_new": is_new,
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "username": user.username,
            "wallet_balance": user.wallet_balance,
            "fee_percent": user.fee_percent,
            "fee_cap": user.fee_cap,
            "api_key_live": user.api_key_live,
            "api_key_test": user.api_key_test,
            "webhook_url": user.webhook_url,
            "free_transactions_left": user.free_transactions_left,
            "free_until": user.free_until.isoformat() if user.free_until else None
        }
    })

    res.set_cookie(
        key="blupal_user_id",
        value=str(user.id),
        httponly=True,
        max_age=86400 * 30,
        samesite="lax"
    )
    return res

@router.post("/auth/magic-link")
async def generate_magic_link(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Generates a 1-click login link for users on the Mini App who want to open
    the desktop dashboard without typing credentials.
    """
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_magic_link_token(user.id)
    verify_url = f"{config.BASE_URL}/auth/verify?token={token}"
    return {
        "success": True,
        "token": token,
        "verify_url": verify_url
    }

@router.get("/miniapp/data")
async def get_miniapp_data(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Returns full fresh data for the Telegram Mini App dashboard.
    """
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sessions = await get_user_sessions(db, user.id)
    active_session = sessions[0] if sessions else None
    invoices = await get_user_invoices(db, user.id, limit=10)

    return {
        "success": True,
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "username": user.username,
            "wallet_balance": user.wallet_balance,
            "fee_percent": user.fee_percent,
            "fee_cap": user.fee_cap,
            "api_key_live": user.api_key_live,
            "api_key_test": user.api_key_test,
            "webhook_url": user.webhook_url,
            "free_transactions_left": user.free_transactions_left,
            "free_until": user.free_until.isoformat() if user.free_until else None
        },
        "session": {
            "card_number": active_session.card_number,
            "phone_number": active_session.phone_number,
            "account_name": active_session.account_name,
            "status": active_session.status
        } if active_session else None,
        "invoices": [
            {
                "id": inv.id,
                "base_amount": inv.base_amount,
                "final_amount": inv.final_amount,
                "status": inv.status,
                "payer_name": inv.payer_name,
                "payment_link": f"{config.BASE_URL}/payment/{inv.public_token}",
                "created_at": inv.created_at.isoformat()
            } for inv in invoices
        ]
    }

@router.post("/dashboard/webhook")
async def update_webhook(payload: WebhookRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await update_user_webhook(db, user_id, payload.webhook_url)
    return {"success": True, "message": "وب‌هوک با موفقیت ذخیره شد."}

@router.post("/dashboard/webhook/test")
async def test_webhook_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    if not user or not user.webhook_url:
        return {"success": False, "message": "ابتدا باید آدرس وب‌هوک را تنظیم کنید."}

    test_payload = {
        "success": True,
        "event": "payment.completed",
        "invoice_id": 9999,
        "status": "PAID",
        "amount": 1000000,
        "final_amount": 1000243,
        "mode": "test",
        "payer_name": "تست وب‌هوک داشبورد",
        "payer_card": "6037991234567890",
        "payer_bank_name": "بانک ملی"
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(user.webhook_url, json=test_payload)
            return {
                "success": resp.status_code == 200,
                "message": f"پاسخ سرور: HTTP {resp.status_code} ({resp.text[:100]})"
            }
    except Exception as e:
        return {"success": False, "message": f"خطا در ارسال به وب‌هوک: {str(e)}"}

@router.post("/dashboard/keys/regenerate")
async def regen_keys(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    live, test = await regenerate_api_keys(db, user_id)
    return {"success": True, "api_key_live": live, "api_key_test": test}

@router.post("/dashboard/invoices/create")
async def create_quick_invoice(payload: QuickInvoiceRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    sessions = await get_user_sessions(db, user_id)

    target_card = sessions[0].card_number if sessions else "6219861012345678"
    session_id = sessions[0].id if sessions else None

    offset, final_amount = await MatchingEngine.allocate_unique_offset(db, target_card, payload.amount)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=config.INVOICE_TTL_MINUTES)

    inv = await create_invoice(
        db=db,
        user_id=user.id,
        card_number=target_card,
        base_amount=payload.amount,
        random_offset=offset,
        final_amount=final_amount,
        expires_at=expires_at,
        mode="live",
        session_id=session_id
    )

    return {
        "success": True,
        "invoice_id": inv.id,
        "amount": inv.base_amount,
        "final_amount": inv.final_amount,
        "payment_link": f"{config.BASE_URL}/payment/{inv.public_token}"
    }

@router.post("/dashboard/wallet/topup")
async def topup_wallet(payload: TopupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    new_balance = await modify_wallet_balance(
        db=db,
        user_id=user_id,
        amount=payload.amount,
        tx_type="DEPOSIT",
        description=f"شارژ کیف پول از داشبورد وب ({payload.amount // 10:,} تومان)"
    )
    return {"success": True, "new_balance": new_balance}

@router.post("/admin/user/{user_id}/fee")
async def update_user_fee(user_id: int, payload: FeeUpdateRequest, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.fee_percent = payload.fee_percent
    user.fee_cap = payload.fee_cap
    await db.commit()
    return {"success": True, "message": "Fee updated successfully"}

# --- BANK SESSION ENDPOINTS (MINI APP & WEB) ---

@router.post("/miniapp/bank/request-otp")
async def miniapp_bank_request_otp(payload: BankOtpRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_phone = "".join([c for c in payload.phone_number if c.isdigit()])
    if len(clean_phone) < 10 or not clean_phone.startswith("09"):
        return JSONResponse({"success": False, "message": "شماره موبایل وارد شده نامعتبر است (مثال: 09121234567)"}, status_code=400)

    client = BluBankClient()
    res = await client.request_otp(clean_phone)
    if not res.get("success"):
        return JSONResponse({"success": False, "message": res.get("message", "ارسال کد تأیید بلوبانک با خطا مواجه شد.")}, status_code=400)

    return {
        "success": True,
        "message": "کد تأیید با موفقیت به شماره شما ارسال گردید.",
        "phone_number": clean_phone,
        "temp_token": res.get("temp_token")
    }

@router.post("/miniapp/bank/verify-otp")
async def miniapp_bank_verify_otp(payload: BankVerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_phone = "".join([c for c in payload.phone_number if c.isdigit()])
    clean_otp = payload.otp.strip()
    if not clean_otp:
        return JSONResponse({"success": False, "message": "لطفاً کد تأیید پیامک‌شده را وارد نمایید."}, status_code=400)

    client = BluBankClient()
    verify_res = await client.verify_otp(clean_phone, clean_otp, payload.temp_token)
    if not verify_res.get("success"):
        return JSONResponse({"success": False, "message": "کد تأیید نامعتبر یا منقضی شده است."}, status_code=400)

    cards_info = await client.get_cards_and_accounts()
    card_data = cards_info.get("cards", [{}])[0]

    card_num = card_data.get("cardNumber", "6219861000000000")
    sheba = card_data.get("sheba", "")
    holder_name = card_data.get("holderName", "کاربر بلوبانک")
    balance = card_data.get("balance", 0)

    token_dict = {
        "access_token": client.access_token,
        "refresh_token": client.refresh_token,
        "device_id": client.device_id,
        "cookies": client.cookies
    }
    encrypted_tokens = encrypt_session_data(token_dict)

    session = await save_bank_session(
        db=db,
        user_id=user_id,
        phone_number=clean_phone,
        card_number=card_num,
        sheba_number=sheba,
        account_name=holder_name,
        encrypted_tokens=encrypted_tokens
    )

    # Optional: Send real-time confirmation via Telegram Bot
    user = await db.get(User, user_id)
    if user and poller_module._bot_instance:
        try:
            card_fmt = " ".join([card_num[i:i+4] for i in range(0, len(card_num), 4)])
            await poller_module._bot_instance.send_message(
                chat_id=user.telegram_id,
                text=(
                    "🎉 <b>نشست فعال بلوبانک با موفقیت در مینی‌اپ ثبت شد!</b>\n\n"
                    f"💳 <b>شماره کارت:</b> <code>{card_fmt}</code>\n"
                    f"👤 <b>صاحب حساب:</b> {holder_name}\n"
                    "🟢 وضعیت: <b>فعال و در حال پایش تراکنش‌های لحظه‌ای</b>"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    return {
        "success": True,
        "message": "نشست فعال بلوبانک با موفقیت برقرار شد!",
        "session": {
            "card_number": card_num,
            "account_name": holder_name,
            "sheba_number": sheba,
            "phone_number": clean_phone,
            "status": "ACTIVE",
            "balance": balance
        }
    }

@router.post("/miniapp/bank/disconnect")
async def miniapp_bank_disconnect(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    sessions = await get_user_sessions(db, user_id)
    for s in sessions:
        await delete_session(db, s.id)

    user = await db.get(User, user_id)
    if user and poller_module._bot_instance:
        try:
            await poller_module._bot_instance.send_message(
                chat_id=user.telegram_id,
                text="⚠️ <b>اتصال نشست بلوبانک با درخواست شما از طریق مینی‌اپ قطع شد.</b>\nجهت فعال‌سازی مجدد تایید خودکار واریزی‌ها، لطفاً نشست جدید ثبت فرمایید.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    return {"success": True, "message": "نشست بلوبانک با موفقیت قطع گردید."}

@router.post("/miniapp/bank/refresh")
async def miniapp_bank_refresh(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    sessions = await get_user_sessions(db, user_id)
    if not sessions:
        return {"success": False, "message": "هیچ نشست فعالی برای این حساب وجود ندارد."}

    session = sessions[0]
    is_valid = await SessionManager.refresh_and_validate(db, session)
    return {
        "success": is_valid,
        "status": session.status,
        "last_balance": session.last_balance,
        "message": "وضعیت نشست با موفقیت بروزرسانی شد." if is_valid else "نشست بلوبانک منقضی شده است. لطفاً مجدداً وارد شوید."
    }
