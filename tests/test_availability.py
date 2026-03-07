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
