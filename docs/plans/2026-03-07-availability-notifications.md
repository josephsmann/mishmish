# Availability Notifications Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow registered users with phone numbers to mark themselves as "available to play" and notify a chosen subset of other users via SMS, with a deep link back to the lobby.

**Architecture:** Server-side availability state in SQLite (`user_availability`, `notify_list_defaults` tables). Three new REST endpoints protected by JWT. Auto-clear on game join and via a background expiry loop. Twilio SMS reuses existing helpers in `auth.py`.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, JWT (PyJWT), Twilio, pytest + TestClient

---

### Task 1: Add DB tables for availability

**Files:**
- Modify: `auth.py` — add new tables to `init_db()`

**Step 1: Write the failing test**

Create `tests/test_availability.py`:

```python
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
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_availability.py::test_availability_tables_created -v
```
Expected: FAIL — tables don't exist yet.

**Step 3: Add tables to `auth.py` `init_db()`**

Add inside the `async with aiosqlite.connect(DB_PATH) as db:` block in `init_db()`, after the existing `CREATE TABLE` statements:

```python
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_availability (
                user_id       TEXT PRIMARY KEY,
                available_until TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notify_list_defaults (
                user_id       TEXT PRIMARY KEY,
                recipient_ids TEXT NOT NULL
            )
        """)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_availability.py::test_availability_tables_created -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add auth.py tests/test_availability.py
git commit -m "feat: add user_availability and notify_list_defaults tables"
```

---

### Task 2: DB helper functions for availability

**Files:**
- Modify: `auth.py` — add four async helper functions

**Step 1: Write the failing tests**

Add to `tests/test_availability.py`:

```python
from datetime import datetime, timezone, timedelta
import auth

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
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_availability.py -k "availability or notify_default" -v
```
Expected: FAIL — functions don't exist yet.

**Step 3: Add helpers to `auth.py`**

Add after the existing SMS section at the bottom of `auth.py`:

```python
# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

async def set_availability(user_id: str, available_until: str) -> None:
    """Upsert availability for a user."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_availability (user_id, available_until, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                available_until = excluded.available_until,
                created_at = excluded.created_at
            """,
            (user_id, available_until, created_at),
        )
        await db.commit()


async def get_availability(user_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_availability WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def clear_availability(user_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_availability WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def clear_expired_availability() -> None:
    """Delete all availability rows where available_until is in the past."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_availability WHERE available_until < ?", (now,)
        )
        await db.commit()


async def save_notify_default(user_id: str, recipient_ids: list) -> None:
    import json as _json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO notify_list_defaults (user_id, recipient_ids)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET recipient_ids = excluded.recipient_ids
            """,
            (user_id, _json.dumps(recipient_ids)),
        )
        await db.commit()


async def get_notify_default(user_id: str) -> Optional[list]:
    import json as _json
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT recipient_ids FROM notify_list_defaults WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    return _json.loads(row["recipient_ids"]) if row else None


async def get_users_with_phones() -> list:
    """Return all users who have a phone number: [{id, username}]."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, username FROM users WHERE phone IS NOT NULL AND phone != ''"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_availability.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add auth.py tests/test_availability.py
git commit -m "feat: add availability DB helper functions"
```

---

### Task 3: SMS helper for availability notifications

**Files:**
- Modify: `auth.py` — add `send_availability_sms()`

**Step 1: Write the failing test**

Add to `tests/test_availability.py`:

```python
from unittest.mock import patch, MagicMock

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
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_availability.py -k "send_availability_sms" -v
```
Expected: FAIL

**Step 3: Add `send_availability_sms` to `auth.py`**

Add after the `send_reset_sms` function:

```python
async def send_availability_sms(to_number: str, from_username: str) -> None:
    """Send an availability notification via Twilio SMS.
    Logs a warning and returns silently if TWILIO_FROM_NUMBER is not set."""
    import logging
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    if not from_number:
        logging.warning(
            f"TWILIO_FROM_NUMBER not set — skipping availability SMS to {to_number}"
        )
        return

    link = f"{APP_BASE_URL}?ready={from_username}"
    body = f"{from_username} is ready to play Mish Mish! Join them: {link}"

    client = _twilio_client()
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: client.messages.create(to=to_number, from_=from_number, body=body),
    )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_availability.py -k "send_availability_sms" -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add auth.py tests/test_availability.py
git commit -m "feat: add send_availability_sms helper"
```

---

### Task 4: JWT auth helper for HTTP endpoints

**Files:**
- Modify: `main.py` — add `_get_current_user()` helper

**Step 1: Write the failing test**

Create `tests/test_availability_endpoints.py`:

```python
import pytest
from fastapi.testclient import TestClient
import auth
import main
from main import app

@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "test.db"))
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    import asyncio
    asyncio.get_event_loop().run_until_complete(auth.init_db())

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
async def registered_user(tmp_path):
    user = await auth.create_user("testuser", "password123", phone="+15551234567")
    token = auth.create_token(user["id"], user["username"])
    return user, token

def test_availability_requires_auth(client):
    resp = client.post("/availability", json={"timeout_minutes": 30, "notify": ["all"]})
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_availability_endpoints.py::test_availability_requires_auth -v
```
Expected: FAIL — endpoint doesn't exist yet (404).

**Step 3: Add `_get_current_user` to `main.py`**

Add after the `_json_ok` helper (around line 75):

```python
async def _get_current_user(request: Request) -> Optional[dict]:
    """Extract and validate JWT from Authorization: Bearer <token> header.
    Returns user dict or None."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    payload = auth.decode_token(token)
    if not payload:
        return None
    return await auth.get_user_by_id(payload["sub"])
```

Also add `from typing import Optional` if not already imported (it is, at line 8).

**Step 4: Run test — still FAIL** (endpoint not yet added, so 404 not 401). That's expected — we'll add endpoints in Task 5.

---

### Task 5: `POST /availability` and `DELETE /availability` endpoints

**Files:**
- Modify: `main.py` — add two endpoints

**Step 1: Write the failing tests**

Add to `tests/test_availability_endpoints.py`:

```python
import asyncio

def make_user_and_token(username="testuser", phone="+15551234567"):
    user = asyncio.get_event_loop().run_until_complete(
        auth.create_user(username, "password123", phone=phone)
    )
    token = auth.create_token(user["id"], user["username"])
    return user, token

def test_post_availability_sets_available(client):
    user, token = make_user_and_token()
    resp = client.post(
        "/availability",
        json={"timeout_minutes": 30, "notify": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    row = asyncio.get_event_loop().run_until_complete(auth.get_availability(user["id"]))
    assert row is not None

def test_post_availability_no_phone_returns_400(client):
    user, token = make_user_and_token(username="nophone", phone=None)
    resp = client.post(
        "/availability",
        json={"timeout_minutes": 30, "notify": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "phone" in resp.json()["error"].lower()

def test_delete_availability_clears(client):
    user, token = make_user_and_token()
    client.post(
        "/availability",
        json={"timeout_minutes": 30, "notify": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.delete(
        "/availability",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    row = asyncio.get_event_loop().run_until_complete(auth.get_availability(user["id"]))
    assert row is None

def test_post_availability_saves_notify_default(client):
    user, token = make_user_and_token()
    user2 = asyncio.get_event_loop().run_until_complete(
        auth.create_user("other", "password123", phone="+15559999999")
    )
    resp = client.post(
        "/availability",
        json={"timeout_minutes": 15, "notify": [user2["id"]]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    default = asyncio.get_event_loop().run_until_complete(auth.get_notify_default(user["id"]))
    assert default == [user2["id"]]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_availability_endpoints.py -v
```
Expected: FAIL — endpoints don't exist.

**Step 3: Add endpoints to `main.py`**

Add after the `/history/players/...` endpoint, before the Admin section:

```python
# ---------------------------------------------------------------------------
# Availability endpoints
# ---------------------------------------------------------------------------

@app.post("/availability")
async def set_availability(request: Request):
    user = await _get_current_user(request)
    if not user:
        return _json_error("Unauthorized", status=401)
    if not user.get("phone"):
        return _json_error("Add a phone number to use this feature")
    if user["id"] in player_games:
        game_id = player_games[user["id"]]
        game = lobby.get_game(game_id)
        if game and game.status in ("waiting", "playing"):
            return _json_error("You're already in a game")

    body = await request.json()
    timeout_minutes = int(body.get("timeout_minutes") or 30)
    timeout_minutes = max(1, min(timeout_minutes, 1440))  # clamp 1min - 24hr
    notify = body.get("notify") or []

    from datetime import datetime, timezone, timedelta
    available_until = (
        datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)
    ).isoformat()
    await auth.set_availability(user["id"], available_until)
    await auth.save_notify_default(user["id"], notify)

    # Resolve recipients
    if notify == ["all"]:
        recipients = await auth.get_users_with_phones()
        recipients = [r for r in recipients if r["id"] != user["id"]]
    else:
        recipients = []
        for uid in notify:
            r = await auth.get_user_by_id(uid)
            if r and r.get("phone") and r["id"] != user["id"]:
                recipients.append(r)

    # Send SMS — best effort, don't fail on Twilio errors
    for recipient in recipients:
        try:
            await auth.send_availability_sms(
                to_number=recipient["phone"],
                from_username=user["username"],
            )
        except Exception as e:
            log.warning(f"SMS to {recipient['id']} failed: {e}")

    return _json_ok({"available_until": available_until, "notified": len(recipients)})


@app.delete("/availability")
async def clear_availability(request: Request):
    user = await _get_current_user(request)
    if not user:
        return _json_error("Unauthorized", status=401)
    await auth.clear_availability(user["id"])
    return _json_ok({"cleared": True})
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_availability_endpoints.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add main.py tests/test_availability_endpoints.py
git commit -m "feat: add POST/DELETE /availability endpoints"
```

---

### Task 6: `GET /users` endpoint

**Files:**
- Modify: `main.py` — add endpoint

**Step 1: Write the failing test**

Add to `tests/test_availability_endpoints.py`:

```python
def test_get_users_returns_names_not_phones(client):
    user, token = make_user_and_token(username="alice")
    asyncio.get_event_loop().run_until_complete(
        auth.create_user("bob", "password123", phone="+15558888888")
    )
    asyncio.get_event_loop().run_until_complete(
        auth.create_user("nophone", "password123", phone=None)
    )
    resp = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    users = resp.json()["users"]
    ids = [u["id"] for u in users]
    assert user["id"] in ids
    # phone must not be present
    for u in users:
        assert "phone" not in u
    # users without phones are excluded
    usernames = [u["username"] for u in users]
    assert "nophone" not in usernames

def test_get_users_requires_auth(client):
    resp = client.get("/users")
    assert resp.status_code == 401
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_availability_endpoints.py -k "get_users" -v
```
Expected: FAIL

**Step 3: Add endpoint to `main.py`**

Add after the `DELETE /availability` endpoint:

```python
@app.get("/users")
async def list_users(request: Request):
    """Return all registered users with phone numbers (id + username only)."""
    user = await _get_current_user(request)
    if not user:
        return _json_error("Unauthorized", status=401)
    users = await auth.get_users_with_phones()
    return _json_ok({"users": [{"id": u["id"], "username": u["username"]} for u in users]})
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_availability_endpoints.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add main.py tests/test_availability_endpoints.py
git commit -m "feat: add GET /users endpoint for recipient picker"
```

---

### Task 7: Auto-clear availability on game join/create

**Files:**
- Modify: `main.py` — clear availability when player joins or creates a game

**Step 1: Write the failing test**

Add to `tests/test_availability_endpoints.py`:

```python
from fastapi.testclient import TestClient

def test_joining_game_clears_availability(client):
    """When a player joins a game via WebSocket, their availability is cleared."""
    user, token = make_user_and_token(username="player1")
    # Set availability
    asyncio.get_event_loop().run_until_complete(
        auth.set_availability(user["id"], "2099-01-01T00:00:00+00:00")
    )
    assert asyncio.get_event_loop().run_until_complete(auth.get_availability(user["id"])) is not None

    # Join a game via WebSocket using player_id (unauthenticated WS flow)
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        temp_pid = msg["player_id"]
        ws.receive_json()  # lobby_state

        # Restore session as the registered user
        ws.send_json({"type": "hello", "saved_player_id": user["id"]})
        ws.receive_json()  # connected
        ws.receive_json()  # lobby_state

        ws.send_json({"type": "create_game", "name": "player1"})
        ws.receive_json()  # joined_game

    assert asyncio.get_event_loop().run_until_complete(auth.get_availability(user["id"])) is None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_availability_endpoints.py::test_joining_game_clears_availability -v
```
Expected: FAIL — availability not cleared yet.

**Step 3: Add `auth.clear_availability` calls in `main.py`**

In `main.py`, find where `create_game` and `join_game` WebSocket messages are handled. After `player_games[player_id] = game_id` is set in each handler, add:

```python
await auth.clear_availability(player_id)
```

Search for both `"create_game"` and `"join_game"` message type handlers and add this line in each.

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_availability_endpoints.py::test_joining_game_clears_availability -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add main.py tests/test_availability_endpoints.py
git commit -m "feat: auto-clear availability when player joins a game"
```

---

### Task 8: Background expiry loop

**Files:**
- Modify: `main.py` — add background task to `startup()`

**Step 1: Write the failing test**

Add to `tests/test_availability_endpoints.py`:

```python
def test_expired_availability_is_cleared(client):
    """Expired rows are removed by the expiry loop."""
    past = "2000-01-01T00:00:00+00:00"
    user, token = make_user_and_token(username="expiring")
    asyncio.get_event_loop().run_until_complete(
        auth.set_availability(user["id"], past)
    )
    # Run clear directly (background loop calls this)
    asyncio.get_event_loop().run_until_complete(auth.clear_expired_availability())
    assert asyncio.get_event_loop().run_until_complete(auth.get_availability(user["id"])) is None
```

**Step 2: Run test to verify it passes immediately** (it tests the helper directly, not the loop)

```bash
uv run pytest tests/test_availability_endpoints.py::test_expired_availability_is_cleared -v
```
Expected: PASS — this test confirms the helper works; the loop wires it up.

**Step 3: Add background loop to `main.py` startup**

Add a new async function before `startup()`:

```python
async def _availability_expiry_loop():
    """Clear expired availability rows every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            await auth.clear_expired_availability()
        except Exception as e:
            log.warning(f"Availability expiry sweep failed: {e}")
```

In the `startup()` function, add at the end:

```python
    asyncio.create_task(_availability_expiry_loop())
```

**Step 4: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add background loop to expire availability after timeout"
```

---

### Task 9: Final integration smoke test

**Step 1: Run the full test suite**

```bash
uv run pytest -v
```
Expected: all PASS, no failures.

**Step 2: Verify the server starts**

```bash
uv run uvicorn main:app --reload &
sleep 2
curl -s http://localhost:8000/users | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
kill %1
```
Expected: `{"ok": False, "error": "Unauthorized"}` (401 — endpoint exists, auth required)

**Step 3: Commit final**

```bash
git add -A
git commit -m "feat: availability notifications feature complete"
```
