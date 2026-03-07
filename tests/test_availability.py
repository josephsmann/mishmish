import asyncio
import pytest
import aiosqlite
import auth
from auth import DB_PATH


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "test.db"))


@pytest.mark.asyncio
async def test_availability_tables_created():
    await auth.init_db()
    async with aiosqlite.connect(auth.DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = {row[0] for row in await cur.fetchall()}
    assert "user_availability" in tables
    assert "notify_list_defaults" in tables


from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_set_and_get_availability():
    await auth.init_db()
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    await auth.set_availability("user1", until)
    row = await auth.get_availability("user1")
    assert row is not None
    assert row["user_id"] == "user1"
    assert row["available_until"] == until


@pytest.mark.asyncio
async def test_clear_availability():
    await auth.init_db()
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    await auth.set_availability("user1", until)
    await auth.clear_availability("user1")
    assert await auth.get_availability("user1") is None


@pytest.mark.asyncio
async def test_clear_expired_availability():
    await auth.init_db()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    await auth.set_availability("user1", past)
    await auth.set_availability("user2", future)
    await auth.clear_expired_availability()
    assert await auth.get_availability("user1") is None
    assert await auth.get_availability("user2") is not None


@pytest.mark.asyncio
async def test_save_and_get_notify_default():
    await auth.init_db()
    await auth.save_notify_default("user1", ["user2", "user3"])
    result = await auth.get_notify_default("user1")
    assert result == ["user2", "user3"]


@pytest.mark.asyncio
async def test_get_notify_default_missing():
    await auth.init_db()
    assert await auth.get_notify_default("nobody") is None


@pytest.mark.asyncio
async def test_send_availability_sms(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.setattr(auth, "APP_BASE_URL", "https://example.com")

    sent = []
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = lambda **kw: sent.append(kw)

    with patch("auth._twilio_client", return_value=mock_client):
        await auth.send_availability_sms(to_number="+15551111111", from_username="alice")

    assert len(sent) == 1
    assert "alice" in sent[0]["body"]
    assert "https://example.com" in sent[0]["body"]
    assert sent[0]["to"] == "+15551111111"


@pytest.mark.asyncio
async def test_send_availability_sms_no_twilio_logs(monkeypatch, caplog):
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    import logging
    with caplog.at_level(logging.WARNING, logger="auth"):
        await auth.send_availability_sms(to_number="+15551111111", from_username="alice")
    assert any("TWILIO_FROM_NUMBER" in m for m in caplog.messages)
