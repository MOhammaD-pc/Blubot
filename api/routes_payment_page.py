import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import get_db
from database.crud import get_invoice_by_token

router = APIRouter()

@router.get("/payment/{token}", response_class=HTMLResponse)
@router.get("/sandbox/payment/{token}", response_class=HTMLResponse)
async def payment_page(token: str, db: AsyncSession = Depends(get_db)):
    invoice = await get_invoice_by_token(db, token)
    if not invoice:
        return HTMLResponse("<h2>فاکتور یافت نشد یا نامعتبر است.</h2>", status_code=404)

    # Format card number in 4-digit blocks
    card_clean = invoice.card_number.replace("-", "").replace(" ", "")
    card_formatted = " ".join([card_clean[i:i+4] for i in range(0, len(card_clean), 4)])

    toman_amount = invoice.base_amount // 10
    toman_final = invoice.final_amount // 10
    offset_toman = invoice.random_offset // 10

    # Remaining seconds
    remaining_seconds = max(0, int((invoice.expires_at - datetime.datetime.utcnow()).total_seconds()))

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>درگاه پرداخت کارت‌به‌کارت هوشمند</title>
    <style>
        * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Vazirmatn, Tahoma, sans-serif; }}
        body {{
            background: linear-gradient(135deg, #0f172a, #1e293b);
            color: #f8fafc;
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 24px;
            max-width: 440px;
            width: 100%;
            padding: 28px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
            backdrop-filter: blur(12px);
            text-align: center;
        }}
        .badge {{
            display: inline-block;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            background: #2563eb;
            color: #fff;
            margin-bottom: 12px;
        }}
        .badge.sandbox {{
            background: #eab308;
            color: #000;
        }}
        h2 {{ margin: 0 0 8px 0; font-size: 20px; color: #fff; }}
        .timer-box {{
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #f87171;
            padding: 8px 16px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: bold;
            margin: 14px 0 20px 0;
        }}
        .bank-card {{
            background: linear-gradient(135deg, #1e40af, #3b82f6);
            border-radius: 18px;
            padding: 22px;
            color: white;
            text-align: right;
            box-shadow: 0 10px 20px rgba(37, 99, 235, 0.3);
            margin-bottom: 20px;
            position: relative;
        }}
        .card-logo {{ font-size: 16px; font-weight: bold; margin-bottom: 18px; display: flex; justify-content: space-between; }}
        .card-num {{
            font-size: 20px;
            letter-spacing: 2px;
            font-family: monospace;
            text-align: center;
            margin: 12px 0;
            direction: ltr;
        }}
        .amount-box {{
            background: rgba(15, 23, 42, 0.8);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 18px;
            border: 1px dashed rgba(255, 255, 255, 0.2);
        }}
        .amount-title {{ font-size: 13px; color: #94a3b8; margin-bottom: 4px; }}
        .amount-val {{ font-size: 24px; font-weight: 800; color: #38bdf8; }}
        .alert-text {{
            font-size: 13px;
            color: #facc15;
            background: rgba(234, 179, 8, 0.1);
            border-radius: 10px;
            padding: 10px;
            margin-bottom: 20px;
            line-height: 1.6;
        }}
        .copy-btn {{
            background: rgba(255, 255, 255, 0.1);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.2);
            padding: 10px 16px;
            border-radius: 12px;
            cursor: pointer;
            width: 100%;
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 10px;
            transition: all 0.2s;
        }}
        .copy-btn:hover {{ background: rgba(255, 255, 255, 0.2); }}
        .success-screen {{ display: none; }}
        .success-icon {{ font-size: 60px; color: #22c55e; margin-bottom: 14px; }}
    </style>
</head>
<body>
    <div class="card" id="main-box">
        <span class="badge {'sandbox' if invoice.mode == 'sandbox' else ''}">
            {'محیط تست (سندباکس)' if invoice.mode == 'sandbox' else 'درگاه امن کارت‌به‌کارت'}
        </span>
        <h2>انتقال وجه به کارت</h2>

        <div class="timer-box" id="timer-text">
            زمان باقی‌مانده: <span id="countdown">--:--</span>
        </div>

        <div class="bank-card">
            <div class="card-logo">
                <span>بلوبانک سامان</span>
                <span>بلوبات</span>
            </div>
            <div class="card-num" id="card-num-text">{card_formatted}</div>
            <div style="font-size: 13px; color: #cbd5e1; text-align: left;">بانک سامان (بلو)</div>
        </div>

        <button class="copy-btn" onclick="copyText('{card_clean}', 'شماره کارت کپی شد!')">📋 کپی شماره کارت</button>

        <div class="amount-box">
            <div class="amount-title">مبلغ دقیق جهت واریز (تومان)</div>
            <div class="amount-val" id="amount-text">{toman_final:,} تومان</div>
            <div style="font-size: 12px; color: #64748b; margin-top: 4px;">معادل {invoice.final_amount:,} ریال</div>
        </div>

        <button class="copy-btn" style="background:#0284c7;" onclick="copyText('{toman_final}', 'مبلغ دقیق کپی شد!')">🔢 کپی مبلغ دقیق</button>

        <div class="alert-text">
            ⚠️ <b>بسیار مهم:</b> لطفاً <b>دقیقاً مبلغ {toman_final:,} تومان</b> را واریز فرمایید تا پرداخت شما به صورت خودکار و در لحظه شناسایی شود.
        </div>
    </div>

    <!-- Success Screen -->
    <div class="card success-screen" id="success-box">
        <div class="success-icon">✓</div>
        <h2 style="color: #22c55e;">پرداخت با موفقیت تأیید شد!</h2>
        <p style="color: #94a3b8; font-size: 14px; margin-top: 10px;">
            تراکنش واریزی شما با موفقیت شناسایی و ثبت گردید.
        </p>
        <div class="amount-box" style="margin-top: 20px;">
            <div class="amount-title">مبلغ واریز شده</div>
            <div class="amount-val" style="color: #22c55e;">{toman_final:,} تومان</div>
        </div>
        <button class="copy-btn" onclick="window.close();" style="margin-top: 16px;">بستن پنجره</button>
    </div>

    <script>
        let seconds = {remaining_seconds};
        const token = "{token}";
        const statusCheckUrl = "/api/v1/payment/check/" + token;

        function updateTimer() {{
            if (seconds <= 0) {{
                document.getElementById("timer-text").innerText = "مهلت پرداخت به اتمام رسیده است.";
                return;
            }}
            const m = Math.floor(seconds / 60).toString().padStart(2, '0');
            const s = (seconds % 60).toString().padStart(2, '0');
            document.getElementById("countdown").innerText = m + ":" + s;
            seconds--;
        }}
        setInterval(updateTimer, 1000);
        updateTimer();

        function copyText(val, msg) {{
            navigator.clipboard.writeText(val);
            alert(msg);
        }}

        // Poll for payment success
        let pollInterval = setInterval(async () => {{
            try {{
                const res = await fetch(statusCheckUrl);
                const data = await res.json();
                if (data.status === "PAID") {{
                    clearInterval(pollInterval);
                    document.getElementById("main-box").style.display = "none";
                    document.getElementById("success-box").style.display = "block";
                }}
            }} catch (e) {{}}
        }}, 2500);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)
