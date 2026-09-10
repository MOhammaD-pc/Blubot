import asyncio
import hashlib
import hmac
import json
import urllib.parse
import sys

# Force UTF-8 on Windows console
sys.stdout.reconfigure(encoding='utf-8')

import httpx
from database.connection import init_db, AsyncSessionLocal
from database.crud import get_or_create_user, get_user_by_telegram_id
from core.telegram_auth import (
    validate_telegram_init_data,
    create_magic_link_token,
    consume_magic_link_token
)
from api.app import app
import config
from database.models import User
from sqlalchemy import select, delete

async def test_all():
    print("==================================================")
    print("🧪 RUNNING TELEGRAM MINI-APP & AUTH TEST SUITE")
    print("==================================================")

    await init_db()

    # Ensure test user is clean before running test
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.telegram_id.in_([77889911, 9911223344])))
        await db.commit()

    # ----------------------------------------------------
    # 1. Test Telegram initData HMAC validation
    # ----------------------------------------------------
    print("\n[1] Testing Telegram WebApp initData HMAC-SHA256 validation...")
    test_bot_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456"
    test_user_payload = {
        "id": 77889911,
        "first_name": "سهراب",
        "username": "sohrab_dev"
    }
    data_dict = {
        "auth_date": "1710000000",
        "query_id": "AAHd9911",
        "user": json.dumps(test_user_payload, separators=(',', ':'))
    }
    # Build data_check_string
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data_dict.items()))
    secret_key = hmac.new(b"WebAppData", test_bot_token.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    data_dict["hash"] = valid_hash
    valid_init_data = urllib.parse.urlencode(data_dict)

    # Validate correct initData
    is_valid, user_data = validate_telegram_init_data(valid_init_data, test_bot_token)
    assert is_valid is True, "Expected valid initData to pass validation"
    assert user_data["id"] == 77889911, f"Expected ID 77889911, got {user_data.get('id')}"
    print("✅ Valid initData verified successfully with HMAC-SHA256.")

    # Validate tampered initData
    tampered_data = valid_init_data.replace("sohrab_dev", "hacker_dev")
    is_invalid, _ = validate_telegram_init_data(tampered_data, test_bot_token)
    assert is_invalid is False, "Expected tampered initData to be rejected"
    print("✅ Tampered initData correctly rejected.")

    # ----------------------------------------------------
    # 2. Test Magic Link generation and consumption
    # ----------------------------------------------------
    print("\n[2] Testing Magic Link Token lifecycle...")
    token = create_magic_link_token(user_id=42)
    assert isinstance(token, str) and len(token) > 20

    # First consumption should succeed
    consumed_user_id = consume_magic_link_token(token)
    assert consumed_user_id == 42, f"Expected user_id=42, got {consumed_user_id}"
    print("✅ Magic link successfully consumed.")

    # Second consumption must fail (single-use)
    reused = consume_magic_link_token(token)
    assert reused is None, "Expected magic link to be invalidated after first use"
    print("✅ Magic link cannot be reused (Single-use verified).")

    # ----------------------------------------------------
    # 3. Test Website Registration Block (BluPal style)
    # ----------------------------------------------------
    print("\n[3] Testing that registration CANNOT happen from website...")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Attempt login with a completely new/unregistered Telegram ID
        unregistered_tg_id = 9911223344
        resp = await client.post("/api/v1/auth/login", json={"identifier": str(unregistered_tg_id)})
        assert resp.status_code == 404, f"Expected 404 for unregistered user, got {resp.status_code}"
        body = resp.json()
        assert body["success"] is False
        assert "ثبت‌نام در بلوبات فقط از طریق ربات و مینی‌اپ" in body["message"]
        print("✅ Web registration correctly blocked: Unregistered user received 404 with Telegram signup message.")

        # Ensure user was NOT created in database
        async with AsyncSessionLocal() as db:
            db_user = await get_user_by_telegram_id(db, unregistered_tg_id)
            assert db_user is None, "User should NOT exist in database after failed web login!"
            print("✅ Verified that no user record was created in database.")

        # ----------------------------------------------------
        # 4. Test Mini-App Registration and Authentication
        # ----------------------------------------------------
        print("\n[4] Testing Registration via Telegram Mini-App...")
        # Configure BOT_TOKEN in config temporarily for testing
        old_token = config.BOT_TOKEN
        config.BOT_TOKEN = test_bot_token

        try:
            # Send valid init_data to /api/v1/auth/miniapp
            mini_resp = await client.post("/api/v1/auth/miniapp", json={"init_data": valid_init_data})
            assert mini_resp.status_code == 200, f"MiniApp auth failed with status {mini_resp.status_code}: {mini_resp.text}"
            mini_body = mini_resp.json()
            assert mini_body["success"] is True
            assert mini_body["is_new"] is True, "First time user should have is_new=True"
            user_info = mini_body["user"]
            assert user_info["telegram_id"] == 77889911
            assert user_info["username"] == "sohrab_dev"
            assert user_info["api_key_live"].startswith("blu_live_")
            assert user_info["fee_percent"] == 2.0
            print(f"✅ User registered via Mini-App: ID={user_info['id']}, Live Key={user_info['api_key_live'][:15]}...")

            # Check that cookie was set
            cookie = mini_resp.cookies.get("blupal_user_id")
            assert cookie == str(user_info["id"]), "Expected blupal_user_id cookie to be set"
            print("✅ Session cookie set for Telegram Mini-App.")

            # Test MiniApp second visit (login, not new)
            second_resp = await client.post("/api/v1/auth/miniapp", json={"init_data": valid_init_data})
            assert second_resp.json()["is_new"] is False
            print("✅ Subsequent Mini-App visits recognize existing user (is_new=False).")

            # Now that user is registered via Telegram, they SHOULD be able to log in on the website!
            print("\n[5] Testing Website login for previously registered Telegram user...")
            web_resp = await client.post("/api/v1/auth/login", json={"identifier": str(77889911)})
            assert web_resp.status_code == 200
            assert web_resp.json()["success"] is True
            print("✅ Registered user can now log into the website with their Telegram ID.")

            # Also test login with Live API Key
            web_key_resp = await client.post("/api/v1/auth/login", json={"api_key": user_info["api_key_live"]})
            assert web_key_resp.status_code == 200
            assert web_key_resp.json()["success"] is True
            print("✅ Registered user can also log in using their API Key.")

            # ----------------------------------------------------
            # 5. Test Magic Link desktop flow
            # ----------------------------------------------------
            print("\n[6] Testing Magic Link desktop browser verification flow...")
            # Generate magic link with authenticated client
            magic_resp = await client.post("/api/v1/auth/magic-link", cookies={"blupal_user_id": str(user_info["id"])})
            assert magic_resp.status_code == 200
            magic_data = magic_resp.json()
            magic_token = magic_data["token"]
            print(f"✅ Magic link token generated: {magic_token[:15]}...")

            # Test consumption via GET /auth/verify?token=...
            verify_resp = await client.get(f"/auth/verify?token={magic_token}", follow_redirects=False)
            assert verify_resp.status_code == 307 or verify_resp.status_code == 302 or verify_resp.status_code == 303
            assert verify_resp.headers["location"] == "/dashboard"
            assert verify_resp.cookies.get("blupal_user_id") == str(user_info["id"])
            print("✅ /auth/verify successfully redeemed token, set cookie, and redirected to /dashboard.")

            # Re-visiting with same token should redirect to login error
            verify_reused = await client.get(f"/auth/verify?token={magic_token}", follow_redirects=False)
            assert "/login?error=invalid_token" in verify_reused.headers["location"]
            print("✅ Expired / used magic link redirected to error.")

            # ----------------------------------------------------
            # 6. Test MiniApp HTML endpoint
            # ----------------------------------------------------
            print("\n[7] Testing /miniapp HTML page rendering...")
            miniapp_page_resp = await client.get("/miniapp")
            assert miniapp_page_resp.status_code == 200
            assert "telegram-web-app.js" in miniapp_page_resp.text
            assert "مینی‌اپ بلوبات" in miniapp_page_resp.text
            print("✅ /miniapp rendered with 200 OK and Telegram WebApp script.")

        finally:
            config.BOT_TOKEN = old_token

    print("\n==================================================")
    print("🎉 ALL MINI-APP & AUTH TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(test_all())
