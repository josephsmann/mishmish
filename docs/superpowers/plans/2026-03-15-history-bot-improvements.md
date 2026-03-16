# History & Bot Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist game history across fly.io restarts, fix inspect_server.py notebook bugs, add opponent-adjustable bot timeout, pre-compute bot moves during the opponent's turn, and track bot timeouts distinctly in game_turns.

**Architecture:** All server changes live in `game.py` (data model) and `main.py` (WebSocket handlers + bot orchestration). The fly.io persistent volume is a config-only change. inspect_server.py is a marimo notebook — edits must only modify the body inside `@app.cell` decorators (marimo handles function signatures and return statements automatically).

**Tech Stack:** FastAPI + Starlette WebSockets, aiosqlite, asyncio, ProcessPoolExecutor, fly.io volumes, marimo notebook

**Spec:** `docs/superpowers/specs/2026-03-15-history-bot-improvements-design.md`

---

## Chunk 1: Infrastructure + Data Model

### Task 1: fly.io Persistent Volume (config only — no tests)

**Files:**
- Modify: `fly.toml`

- [ ] **Step 1: Add the `[[mounts]]` block to fly.toml**

Open `fly.toml` and add after the `[[vm]]` section:

```toml
[[mounts]]
  source = "mishmish_data"
  destination = "/data"
```

- [ ] **Step 2: Verify fly.toml is valid TOML**

```bash
uv run python3 -c "import tomllib; tomllib.load(open('fly.toml','rb')); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add fly.toml
git commit -m "infra: add fly.io persistent volume mount for DB"
```

> **Note — manual one-time production steps (do NOT automate):**
> ```bash
> fly volumes create mishmish_data --region ord --size 1
> fly secrets set DB_PATH=/data/mishmish.db
> fly deploy --ha=false
> ```
> Run these manually after the full feature branch is merged.

---

### Task 2: Add `bot_timeout_seconds` to Game

**Files:**
- Modify: `game.py`
- Modify: `tests/test_game.py` (create if absent)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_game.py` (or append if it exists):

```python
"""Tests for Game data model changes."""
import pytest
from game import Game


def test_bot_timeout_seconds_default():
    g = Game(game_id="g1", creator_id="p1")
    assert g.bot_timeout_seconds == 10.0


def test_bot_timeout_seconds_survives_round_trip():
    g = Game(game_id="g1", creator_id="p1")
    g.bot_timeout_seconds = 25.0
    g2 = Game.from_dict(g.to_dict())
    assert g2.bot_timeout_seconds == 25.0


def test_bot_timeout_seconds_defaults_on_missing_key():
    """Old serialized games without the key should default to 10.0."""
    g = Game(game_id="g1", creator_id="p1")
    d = g.to_dict()
    del d["bot_timeout_seconds"]
    g2 = Game.from_dict(d)
    assert g2.bot_timeout_seconds == 10.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_game.py -v
```

Expected: 3 failures (AttributeError or similar — field doesn't exist yet)

- [ ] **Step 3: Add `bot_timeout_seconds` to `Game.__init__`**

In `game.py`, inside `__init__`, after `self.last_activity`:

```python
self.bot_timeout_seconds: float = 10.0
```

- [ ] **Step 4: Add to `to_dict`**

In `game.py`, in `to_dict()`, add to the returned dict:

```python
"bot_timeout_seconds": self.bot_timeout_seconds,
```

- [ ] **Step 5: Add to `from_dict`**

In `game.py`, in `from_dict()`, after restoring `last_activity`:

```python
g.bot_timeout_seconds = float(d.get("bot_timeout_seconds", 10.0))
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
uv run pytest tests/test_game.py -v
```

Expected: 3 PASSED

- [ ] **Step 7: Run full test suite to check no regressions**

```bash
uv run pytest -v
```

Expected: all previously-passing tests still pass

- [ ] **Step 8: Commit**

```bash
git add game.py tests/test_game.py
git commit -m "feat: add bot_timeout_seconds to Game model"
```

---

## Chunk 2: main.py — Bot Timeout Control, Pre-computation, Timeout Tracking

### Task 3: `set_bot_timeout` WebSocket Message

**Files:**
- Modify: `main.py`
- Modify: `tests/test_bot_timeout.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_bot_timeout.py`:

```python
"""Tests for the set_bot_timeout WebSocket message."""
import os
import pytest
from starlette.testclient import TestClient

os.environ.setdefault("ADMIN_KEY", "test-key")


@pytest.fixture()
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def _join_and_start(client):
    """Helper: create a game with a bot and start it. Returns (ws, game_id)."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        assert game_id is not None
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        # Drain until playing
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break
        return game_id


def test_set_bot_timeout_updates_game(client):
    """Human player can set bot timeout; value is clamped to [2, 60]."""
    from lobby import Lobby
    import main
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        assert game_id
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 30.0})
        # Give server a moment to apply
        import time; time.sleep(0.1)

        game = main.lobby.get_game(game_id)
        assert game is not None
        assert game.bot_timeout_seconds == 30.0


def test_set_bot_timeout_clamps_low(client):
    import main
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 0.1})
        import time; time.sleep(0.1)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 2.0


def test_set_bot_timeout_clamps_high(client):
    import main
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 999.0})
        import time; time.sleep(0.1)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 60.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_bot_timeout.py -v
```

Expected: 3 failures — message type `set_bot_timeout` not handled

- [ ] **Step 3: Add `set_bot_timeout` handler to `main.py`**

In `main.py`, in the WebSocket message dispatch (the `elif msg_type == ...` chain), add a new branch. A good place is after the `add_bot` handler:

```python
elif msg_type == "set_bot_timeout":
    game_id = player_games.get(player_id)
    if not game_id:
        await send(ws, {"type": "error", "message": "Not in a game"})
        continue
    game = lobby.get_game(game_id)
    if game is None or game.status != "playing":
        await send(ws, {"type": "error", "message": "No active game"})
        continue
    # Only non-bot players may adjust the timeout
    requester = next((p for p in game.players if p["id"] == player_id), None)
    if requester is None or requester.get("is_bot"):
        await send(ws, {"type": "error", "message": "Not allowed"})
        continue
    seconds = float(msg.get("seconds", 10.0))
    game.bot_timeout_seconds = max(2.0, min(60.0, seconds))
    log.info("set_bot_timeout: pid=%s game=%s seconds=%s", player_id, game_id, game.bot_timeout_seconds)
```

- [ ] **Step 4: Replace hardcoded timeout in `trigger_bot_if_needed`**

Find this line in `main.py` (around line 557):
```python
new_table = await asyncio.wait_for(asyncio.wrap_future(_future), timeout=10.0)
```

Replace with:
```python
new_table = await asyncio.wait_for(asyncio.wrap_future(_future), timeout=game.bot_timeout_seconds)
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
uv run pytest tests/test_bot_timeout.py -v
```

Expected: 3 PASSED

- [ ] **Step 6: Run full suite**

```bash
uv run pytest -v
```

Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_bot_timeout.py
git commit -m "feat: add set_bot_timeout WebSocket message and use game.bot_timeout_seconds"
```

---

### Task 4: Bot Pre-computation During Opponent's Turn

**Files:**
- Modify: `main.py`

No isolated unit tests possible for the async precomp flow — we verify via integration smoke test after implementation.

- [ ] **Step 1: Add `_bot_precomp` dict alongside `_bot_pending`**

In `main.py`, find:
```python
_bot_pending: Dict[str, "Future"] = {}   # game_id -> submitted cf.Future
```

Add immediately after:
```python
_bot_precomp: Dict[str, "Future"] = {}   # game_id -> speculative precomp future
```

- [ ] **Step 2: Clear `_bot_precomp` in the pool-reset branch**

In `trigger_bot_if_needed`, find the pool-reset block (around line 563):
```python
_bot_pool.shutdown(wait=False)
_bot_pool = ProcessPoolExecutor(max_workers=2)
_bot_pending.clear()
```

Add `_bot_precomp.clear()` after `_bot_pending.clear()`:
```python
_bot_pool.shutdown(wait=False)
_bot_pool = ProcessPoolExecutor(max_workers=2)
_bot_pending.clear()
_bot_precomp.clear()
```

- [ ] **Step 3: Add `_precompute_for_bot` helper function**

Add this new async function in `main.py` before `trigger_bot_if_needed`:

```python
async def _precompute_for_bot(game_id: str):
    """Speculatively submit bot search during the opponent's turn.

    The result is stored in _bot_precomp[game_id] and consumed (or discarded)
    by trigger_bot_if_needed when the bot's turn arrives.
    """
    global _bot_pool
    game = lobby.get_game(game_id)
    if game is None or game.status != "playing":
        return
    current = game._get_current_player()
    if current is None or not current.get("is_bot"):
        return
    bot_id = current["id"]
    bot_version = current.get("bot_version", bot.DEFAULT)
    try:
        _future = _bot_pool.submit(find_best_play, current["hand"], game.table, bot_version)
        _bot_precomp[game_id] = _future
        # Also register in _bot_pending under a prefixed key so pool-reset
        # stranded-future sweep can see it (the sweep skips precomp_ keys
        # when deciding which games to re-trigger).
        _bot_pending[f"precomp_{game_id}"] = _future
        log.info("bot precomp started: bot=%s game=%s", bot_id, game_id)
    except Exception as exc:
        log.warning("bot precomp submit failed: game=%s: %s", game_id, exc)
```

- [ ] **Step 4: Schedule precomp after each human draw/play**

In the `draw_card` handler, after `await broadcast_game_state(game_id)` (and before `await cleanup_ended_game(game_id)`), add:

```python
asyncio.create_task(_precompute_for_bot(game_id))
```

Do the same in the `play_turn` handler, in the same position (after `broadcast_game_state`, before `cleanup_ended_game`).

The full draw_card handler tail should look like:
```python
if _drawing_player:
    await record_turn(game, _drawing_player['name'], "draw")
await broadcast_game_state(game_id)
asyncio.create_task(_precompute_for_bot(game_id))
await cleanup_ended_game(game_id)
await trigger_bot_if_needed(game_id)
```

And similarly for play_turn.

- [ ] **Step 5: Consume precomp result in `trigger_bot_if_needed`**

In `trigger_bot_if_needed`, find the section that computes `state_key` and then submits to the pool (around lines 541–557). Replace it with:

```python
hand_key = tuple(sorted((c['rank'], c['suit']) for c in current['hand']))
table_key = tuple(sorted((c['rank'], c['suit']) for meld in game.table for c in meld))
state_key = (hand_key, table_key)
if _bot_last_draw_state.get(game_id) == state_key:
    log.info("bot draw_card (no change): bot=%s game=%s", bot_id, game_id)
    game.draw_card(bot_id)
    await record_turn(game, current['name'], "draw")
    await broadcast_game_state(game_id)
    await cleanup_ended_game(game_id)
    await trigger_bot_if_needed(game_id)
    return

# Check for a ready precomp result from the opponent's turn
precomp_future = _bot_precomp.pop(game_id, None)
_bot_pending.pop(f"precomp_{game_id}", None)

if precomp_future is not None and precomp_future.done() and precomp_future.exception() is None:
    precomp_table_key = tuple(sorted((c['rank'], c['suit']) for meld in game.table for c in meld))
    # Recompute table_key from current state (may have changed since precomp submitted)
    # hand_key was computed from current hand above — that hasn't changed since precomp
    if precomp_table_key == table_key:
        # Table unchanged: use precomp result for free
        new_table = precomp_future.result()
        log.info("bot using precomp result: bot=%s game=%s", bot_id, game_id)
    else:
        # Table changed: discard and run fresh
        precomp_future = None
        new_table = None  # will be overwritten below
else:
    precomp_future = None
    new_table = None

if precomp_future is None:
    # No usable precomp — submit fresh or wait for still-running precomp
    # (Re-check in case it's still running — unlikely but possible)
    bot_version = current.get('bot_version', bot.DEFAULT)
    _future = _bot_pool.submit(find_best_play, current['hand'], game.table, bot_version)
    _bot_pending[game_id] = _future
    try:
        new_table = await asyncio.wait_for(asyncio.wrap_future(_future), timeout=game.bot_timeout_seconds)
    except asyncio.TimeoutError:
        if not _future.cancel():
            log.warning("bot timed out (running), resetting pool: bot=%s game=%s", bot_id, game_id)
            stranded = [gid for gid, f in _bot_pending.items()
                        if gid != game_id and not gid.startswith("precomp_") and not f.done()]
            _bot_pool.shutdown(wait=False)
            _bot_pool = ProcessPoolExecutor(max_workers=2)
            _bot_pending.clear()
            _bot_precomp.clear()
            for gid in stranded:
                log.info("re-triggering bot after pool reset: game=%s", gid)
                asyncio.get_event_loop().create_task(trigger_bot_if_needed(gid))
        else:
            log.warning("bot timed out (queued), cancelled: bot=%s game=%s", bot_id, game_id)
        new_table = None
        _bot_pending.pop(game_id, None)
    else:
        _bot_pending.pop(game_id, None)
```

> **Note:** The original code has a `finally: _bot_pending.pop(game_id, None)` block — remove it since we now handle cleanup explicitly in each branch above.

- [ ] **Step 6: Cleanup `_bot_precomp` in `cleanup_ended_game` and `abort_game`**

In `cleanup_ended_game`, after `_bot_last_draw_state.pop(game_id, None)`, add:
```python
_bot_precomp.pop(game_id, None)
_bot_pending.pop(f"precomp_{game_id}", None)
```

In the `abort_game` handler (in the WebSocket dispatch), just before `lobby.remove_game(game_id)`, add all three cleanup lines (note: `abort_game` currently does not clean up `_bot_last_draw_state` at all — fix that pre-existing gap here too):
```python
_bot_last_draw_state.pop(game_id, None)
_bot_precomp.pop(game_id, None)
_bot_pending.pop(f"precomp_{game_id}", None)
```

- [ ] **Step 7: Smoke test the precomp flow locally**

```bash
uv run uvicorn main:app --port 8080 --log-level info &
sleep 2
uv run python3 -c "
import asyncio, json, websockets

async def run():
    async with websockets.connect('ws://localhost:8080/ws') as ws:
        for _ in range(3):
            try: await asyncio.wait_for(ws.recv(), timeout=1)
            except asyncio.TimeoutError: break
        await ws.send(json.dumps({'type': 'create_game', 'name': 'Tester'}))
        game_id = None
        for _ in range(5):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                if msg.get('type') == 'joined_game':
                    game_id = msg['game_id']
            except asyncio.TimeoutError: break
        await ws.send(json.dumps({'type': 'add_bot', 'version': 'v1'}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({'type': 'start_game'}))
        turns = 0
        for _ in range(100):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                gs = msg.get('state', {})
                if not gs: continue
                if gs.get('your_turn'): await ws.send(json.dumps({'type': 'draw_card'}))
                turns += 1
                if gs.get('status') == 'ended':
                    print(f'Game ended in {turns} turns. Winner: {gs.get(\"winner\") or \"draw\"}')
                    break
            except asyncio.TimeoutError:
                print('Timeout — bot may be stuck')
                break

asyncio.run(run())
"
pkill -f "uvicorn main:app"
```

Expected: game completes, no timeout messages

- [ ] **Step 8: Run full test suite**

```bash
uv run pytest -v
```

Expected: all passing

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "feat: pre-compute bot moves during opponent's turn"
```

---

### Task 5: Track Bot Timeouts as `timeout_draw`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Change timeout action string**

In `trigger_bot_if_needed`, find where `new_table = None` is set after `asyncio.TimeoutError` and the bot subsequently draws. The draw call is followed by:

```python
await record_turn(game, current['name'], "draw")
```

This happens in the branch `if new_table is None:` (around line 574). Change it to check whether a timeout occurred:

The cleanest way: introduce a boolean `_timed_out = False` before the `asyncio.wait_for` call, set it to `True` in the `except asyncio.TimeoutError` block, then use it when recording:

In the precomp-is-None branch, before `asyncio.wait_for`, add:
```python
_timed_out = False
```

In the `except asyncio.TimeoutError:` block, after `new_table = None`, add:
```python
_timed_out = True
```

Then in the `if new_table is None:` block where `record_turn` is called:
```python
_draw_action = "timeout_draw" if _timed_out else "draw"
await record_turn(game, current['name'], _draw_action)
```

Also initialize `_timed_out = False` for the precomp-result path (before the `if precomp_future is None:` block) so the variable always exists.

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all passing

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: record bot timeout draws as 'timeout_draw' in game_turns"
```

---

## Chunk 3: inspect_server.py Notebook Fixes

> **Marimo editing rule:** Only modify the body inside `@app.cell` function bodies. Do NOT add/remove function parameters or return statements — marimo manages those. Each edit replaces cell body content only.

### Task 6: Fix `player_name` Field (3 Call Sites)

**Files:**
- Modify: `inspect_server.py`

- [ ] **Step 1: Fix history table cell (line ~163)**

Find the cell that builds `history_table`. Change:
```python
", ".join(p.get("name", "") if isinstance(p, dict) else str(p)
          for p in g.get("players", []))
```
To:
```python
", ".join(p.get("player_name", "") if isinstance(p, dict) else str(p)
          for p in g.get("players", []))
```

- [ ] **Step 2: Fix game detail header cell (line ~286)**

Find the cell that builds the game detail markdown table. Change:
```python
_names = [p.get("name", "") if isinstance(p, dict) else str(p) for p in _players]
```
To:
```python
_names = [p.get("player_name", p.get("name", "")) if isinstance(p, dict) else str(p) for p in _players]
```

(Fallback to `"name"` keeps live game compatibility — live game state uses `"name"` on player dicts.)

- [ ] **Step 3: Fix card view cell player loop (line ~354)**

Find the cell that renders the card view HTML. Change:
```python
_parts.append(f"<b>{_p.get('name','?')}</b> — {len(_hand)} cards: {_hand_html}<br>")
```
To:
```python
_pname = _p.get("name") or _p.get("player_name") or "?"
_parts.append(f"<b>{_pname}</b> — {len(_hand)} cards: {_hand_html}<br>")
```

- [ ] **Step 4: Verify marimo syntax**

```bash
uv run marimo check inspect_server.py
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add inspect_server.py
git commit -m "fix: use player_name field for history games in inspect_server"
```

---

### Task 7: History Card View — Final State Fallback from game_turns

**Files:**
- Modify: `inspect_server.py`

The card view cell (renders table + player hands) currently runs before the game_turns fetch cell, so `game_turns` isn't available as a dependency. We need to reorder: move the game_turns fetch cell above the card view cell.

- [ ] **Step 1: Move the game_turns fetch cell above the card view cell**

In `inspect_server.py`, the game_turns fetch cell currently looks like:

```python
@app.cell(hide_code=True)
def _(BASE_URL, game_detail, get_selected, httpx):
    game_detail
    _sel = get_selected()
    game_turns = []
    if _sel is not None:
        _r = httpx.get(f"{BASE_URL}/history/games/{_sel['game_id']}/turns", timeout=10)
        if _r.is_success:
            game_turns = _r.json().get("turns", [])
    return (game_turns,)
```

And the card view cell is just above it. **Swap their positions** in the file — move the game_turns fetch cell to be immediately before the card view cell, so `game_turns` is defined first.

- [ ] **Step 2: Add `game_turns` as a parameter and fallback in the card view cell**

The card view cell signature will gain `game_turns` as a parameter (marimo infers this from variable references in the cell body). In the cell body, add the fallback logic:

Replace the existing lines that read table and players data:
```python
# Live games use "table"/"hand"; history games use "final_table"/"final_hand"
_melds = game_detail.get("final_table") or game_detail.get("table") or []
_players = game_detail.get("players", [])
```

With:
```python
# Live games carry table/hand in game_detail.
# History games don't — fall back to last turn in game_turns.
_melds = game_detail.get("table") or []
_players = game_detail.get("players", [])

if not _melds and game_turns:
    _last = game_turns[-1]
    _melds = _last.get("table", [])
    # Merge final hands into player dicts for display
    _final_hands = _last.get("hands", {})
    _players = [
        {**p, "_final_hand": _final_hands.get(p.get("player_name") or p.get("name", ""), [])}
        for p in _players
    ]
```

Then update the player hand rendering loop to use `_final_hand` when present:
```python
for _p in _players:
    _hand = _p.get("hand") or _p.get("_final_hand") or []
```

- [ ] **Step 3: Verify marimo syntax**

```bash
uv run marimo check inspect_server.py
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add inspect_server.py
git commit -m "fix: show final table and hands for history games in card view"
```

---

### Task 8: `timeout_draw` Badge in Turn History

**Files:**
- Modify: `inspect_server.py`

- [ ] **Step 1: Add amber badge for `timeout_draw`**

Find the turn history cell that builds the action badge HTML:
```python
_action_badge = (
    '<span style="background:#4caf50;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">play</span>'
    if _t["action"] == "play" else
    '<span style="background:#2196f3;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">draw</span>'
)
```

Replace with:
```python
if _t["action"] == "play":
    _action_badge = '<span style="background:#4caf50;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">play</span>'
elif _t["action"] == "timeout_draw":
    _action_badge = '<span style="background:#e67e22;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">timeout</span>'
else:
    _action_badge = '<span style="background:#2196f3;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">draw</span>'
```

- [ ] **Step 2: Verify marimo syntax**

```bash
uv run marimo check inspect_server.py
```

Expected: no errors

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest -v
```

Expected: all passing

- [ ] **Step 4: Final commit**

```bash
git add inspect_server.py
git commit -m "feat: show timeout_draw as distinct amber badge in turn history"
```

---

## Final Checklist

- [ ] All tests pass: `uv run pytest -v`
- [ ] `marimo check inspect_server.py` clean
- [ ] fly.toml has `[[mounts]]` block
- [ ] Reminder: run manual fly.io one-time steps after merge:
  ```bash
  fly volumes create mishmish_data --region ord --size 1
  fly secrets set DB_PATH=/data/mishmish.db
  fly deploy --ha=false
  ```
