import asyncio
import datetime
import sys

# Force UTF-8 on Windows console
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import init_db, AsyncSessionLocal
from database.crud import (
    get_or_create_user,
    save_bank_session,
    create_invoice,
    get_invoice_by_id,
    modify_wallet_balance
)
from database.models import User
from core.matching_engine import MatchingEngine
from core.wallet_service import WalletService
from blubank.client import BluTransaction
from blubank.crypto import encrypt_session_data, decrypt_session_data
import httpx
from api.app import app

async def run_tests():
    print("========================================")
    print("🚀 STARTING BLUPAL PLATFORM TEST SUITE")
    print("========================================")

    # 1. DB Init
    print("\n[1] Testing Database Initialization...")
    await init_db()
    print("✅ Database initialized successfully.")

    async with AsyncSessionLocal() as db:
        # 2. User & Free Trial
        print("\n[2] Testing User Creation and Free Trial...")
        user, is_new = await get_or_create_user(db, telegram_id=987654321, username="test_merchant", first_name="Ali")
        print(f"✅ User ID={user.id}, Live Key={user.api_key_live[:15]}..., Free Until={user.free_until}")

        # 3. Wallet and Commission Engine
        print("\n[3] Testing Commission Engine & Free Trial Logic...")
        # Reset trial for idempotence in test
        user.free_until = datetime.datetime.utcnow() + datetime.timedelta(days=30)
        user.free_transactions_left = 50
        await db.commit()

        # Free trial test:
        fee_trial, reason_trial = WalletService.calculate_commission(user, 10_000_000)  # 1,000,000 Tomans
        assert fee_trial == 0, f"Expected 0 during trial, got {fee_trial}"
        print(f"✅ Free Trial check passed: Fee={fee_trial} Rials ({reason_trial})")

        # Post-trial test:
        user.free_until = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        user.free_transactions_left = 0
        await db.commit()

        # 2% of 500,000 Rials (50,000 Tomans) is 10,000 Rials (1,000 Tomans)
        fee_normal, reason_normal = WalletService.calculate_commission(user, 500_000)
        assert fee_normal == 10_000, f"Expected 10,000, got {fee_normal}"
        print(f"✅ Normal 2% Fee check passed: Fee={fee_normal} Rials on 500,000 Rials")

        # Ceiling cap test: 2% of 50,000,000 Rials is 1,000,000 Rials, but cap is 350,000 Rials (35,000 Tomans)
        fee_capped, reason_capped = WalletService.calculate_commission(user, 50_000_000)
        assert fee_capped == 350_000, f"Expected cap of 350,000, got {fee_capped}"
        print(f"✅ Fee Cap check passed: Fee={fee_capped} Rials (Cap hit correctly)")

        # Top up wallet
        print("\n[4] Testing Prepaid Wallet Top-up & Deduction...")
        new_balance = await WalletService.top_up_wallet(db, user.id, 500_000, "شارژ تستی اولیه")
        print(f"✅ Wallet topped up: New Balance={new_balance:,} Rials ({new_balance // 10:,} Tomans)")

        # 4. Bank Session & Encryption
        print("\n[5] Testing Bank Session AES Encryption...")
        sample_tokens = {"access_token": "secret_jwt_token_123", "device_id": "iphone_test"}
        enc = encrypt_session_data(sample_tokens)
        dec = decrypt_session_data(enc)
        assert dec["access_token"] == "secret_jwt_token_123"
        print(f"✅ AES Encryption & Decryption verified. Ciphertext length: {len(enc)}")

        session = await save_bank_session(
            db=db,
            user_id=user.id,
            phone_number="09120000000",
            card_number="6219861099998888",
            encrypted_tokens=enc,
            sheba_number="IR120170000000123456789001",
            account_name="علی رضایی"
        )
        print(f"✅ Bank Session saved for Card={session.card_number}, Owner={session.account_name}")

        # 5. Matching Engine & Unique Offsets
        print("\n[6] Testing Unique Offset Allocation for Card...")
        base_amt = 1_000_000  # 100,000 Tomans
        offset1, final1 = await MatchingEngine.allocate_unique_offset(db, session.card_number, base_amt)
        inv1 = await create_invoice(
            db=db,
            user_id=user.id,
            card_number=session.card_number,
            base_amount=base_amt,
            random_offset=offset1,
            final_amount=final1,
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=20),
            session_id=session.id
        )

        offset2, final2 = await MatchingEngine.allocate_unique_offset(db, session.card_number, base_amt)
        assert offset1 != offset2, "Offsets must be unique across active invoices!"
        print(f"✅ Invoices created with distinct offsets: Invoice #{inv1.id} -> {final1} Rials, Next -> offset {offset2}")

        # 6. Matching Incoming Transaction
        print("\n[7] Testing Incoming Deposit Matching & Auto Settlement...")
        fake_tx = BluTransaction(
            amount=final1,
            is_deposit=True,
            tracking_number="TRACK_987654321",
            date_time="1405-01-01 12:00:00",
            description="انتقال کارت به کارت",
            payer_name="محمد محمدی",
            payer_card="6037991122334455",
            payer_bank="بانک ملی",
            balance_after=55_000_000
        )

        match_result = await MatchingEngine.match_and_process_deposit(db, session.card_number, fake_tx)
        assert match_result is not None, "Transaction should match pending invoice!"
        matched_invoice, fee_charged, is_low = match_result

        assert matched_invoice.status == "PAID"
        assert matched_invoice.payer_name == "محمد محمدی"
        assert matched_invoice.bank_track_id == "TRACK_987654321"
        print(f"✅ Deposit Matched Successfully! Invoice #{matched_invoice.id} status={matched_invoice.status}")
        print(f"   Payer: {matched_invoice.payer_name}, Card: {matched_invoice.payer_card}, Fee charged: {fee_charged} Rials")

    # 7. Test FastAPI Endpoints with HTTPX AsyncClient
    print("\n[8] Testing REST API Endpoints (BluPal Compatible)...")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create Invoice in Sandbox
        create_res = await client.post(
            "/api/v1/invoices/create",
            headers={"X-API-Key": user.api_key_test},
            json={"amount": 2_000_000}
        )
        assert create_res.status_code == 200, f"Create invoice failed: {create_res.text}"
        inv_data = create_res.json()
        assert inv_data["success"] is True
        inv_id = inv_data["invoice_id"]
        print(f"✅ POST /api/v1/invoices/create -> Success! Invoice ID={inv_id}, Final Amount={inv_data['final_amount']}")

        # Query Invoice Status
        status_res = await client.get(
            f"/api/v1/invoices/{inv_id}",
            headers={"X-API-Key": user.api_key_test}
        )
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "PENDING"
        print(f"✅ GET /api/v1/invoices/{inv_id} -> Status is PENDING")

        # Simulate Payment in Sandbox
        sim_res = await client.post(
            f"/api/v1/sandbox/invoices/{inv_id}/simulate",
            headers={"X-API-Key": user.api_key_test},
            json={"scenario": "success"}
        )
        assert sim_res.status_code == 200
        assert sim_res.json()["status"] == "PAID"
        print(f"✅ POST /api/v1/sandbox/invoices/{inv_id}/simulate -> Status transitioned to PAID")

        # Public Payment Page HTML
        public_token = inv_data["payment_link"].split("/")[-1]
        page_res = await client.get(f"/payment/{public_token}")
        assert page_res.status_code == 200
        assert "درگاه پرداخت کارت‌به‌کارت" in page_res.text
        print("✅ GET /payment/{token} -> HTML Payment Checkout page rendered with 200 OK")

    print("\n========================================")
    print("🎉 ALL TEST CASES PASSED SUCCESSFULLY!")
    print("========================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
