import datetime
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.connection import get_db
from database.models import User, BankSession, Invoice, WalletLedger
from database.crud import get_user_sessions, get_user_invoices
from core.telegram_auth import consume_magic_link_token

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(include_in_schema=False)

def get_session_user_id(request: Request) -> int | None:
    cookie_val = request.cookies.get("blupal_user_id")
    if cookie_val and cookie_val.isdigit():
        return int(cookie_val)
    return None

@router.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )

@router.get("/documentation", response_class=HTMLResponse)
async def documentation_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="documentation.html",
        context={
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )

@router.get("/miniapp", response_class=HTMLResponse)
async def miniapp_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="miniapp.html",
        context={
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )

@router.get("/auth/verify")
async def verify_magic_link(token: str):
    user_id = consume_magic_link_token(token)
    if not user_id:
        return RedirectResponse(url="/login?error=invalid_token")

    res = RedirectResponse(url="/dashboard")
    res.set_cookie(
        key="blupal_user_id",
        value=str(user_id),
        httponly=True,
        max_age=86400 * 30,
        samesite="lax"
    )
    return res

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user_id = get_session_user_id(request)
    if user_id:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )

@router.get("/logout")
async def logout():
    res = RedirectResponse(url="/login")
    res.delete_cookie("blupal_user_id")
    return res

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        return RedirectResponse(url="/login")

    user = await db.get(User, user_id)
    if not user:
        res = RedirectResponse(url="/login")
        res.delete_cookie("blupal_user_id")
        return res

    sessions = await get_user_sessions(db, user.id)
    active_session = sessions[0] if sessions else None

    invoices = await get_user_invoices(db, user.id, limit=20)

    # Count paid invoices
    paid_stmt = select(func.count(Invoice.id)).where(
        Invoice.user_id == user.id,
        Invoice.status == "PAID"
    )
    res_paid = await db.execute(paid_stmt)
    paid_count = res_paid.scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "session": active_session,
            "invoices": invoices,
            "paid_count": paid_count,
            "now": datetime.datetime.utcnow(),
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    users_stmt = select(User).order_by(User.id.desc()).limit(50)
    res_users = await db.execute(users_stmt)
    users = list(res_users.scalars().all())

    # Metrics
    res_fees = await db.execute(select(func.sum(WalletLedger.amount)).where(WalletLedger.type == "COMMISSION"))
    total_fees = abs(res_fees.scalar() or 0)

    res_vol = await db.execute(select(func.sum(Invoice.final_amount)).where(Invoice.status == "PAID"))
    total_volume = res_vol.scalar() or 0

    res_paid_cnt = await db.execute(select(func.count(Invoice.id)).where(Invoice.status == "PAID"))
    paid_cnt = res_paid_cnt.scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "users": users,
            "total_users": len(users),
            "total_fees": total_fees,
            "total_volume": total_volume,
            "paid_invoices_count": paid_cnt,
            "base_url": config.BASE_URL,
            "bot_username": config.BOT_USERNAME
        }
    )
