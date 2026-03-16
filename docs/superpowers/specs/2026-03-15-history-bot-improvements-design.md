# Design: History Persistence, Bot Timeout Control & Pre-computation

**Date:** 2026-03-15
**Status:** Approved

---

## Problem Summary

1. **History not persisting** — fly.io uses ephemeral storage by default. Every machine stop/restart wipes `mishmish.db`, losing all game history and turn records.
2. **inspect_server.py notebook bugs** — History player names use wrong field key; history game detail card view has no fallback for final table/hands.
3. **Bot timeout not adjustable** — Hardcoded 10-second budget; human opponent cannot tune it.
4. **Bot wastes its entire budget** — Pre-computation only starts when it's the bot's turn; the opponent's turn is idle compute time.
5. **No timeout tracking** — All bot draws look identical in `game_turns`; timeouts are indistinguishable from "no valid play found" draws.

---

## Changes

### 1. fly.io Persistent Volume

**fly.toml** — add mount:
```toml
[[mounts]]
  source = "mishmish_data"
  destination = "/data"
```

**auth.py** — already reads `DB_PATH` from env, no code change needed.

**One-time deployment steps (manual):**
```bash
fly volumes create mishmish_data --region ord --size 1
fly secrets set DB_PATH=/data/mishmish.db
fly deploy --ha=false
```

No data migration needed (no production history worth keeping yet).

---

### 2. inspect_server.py Bug Fixes

**Bug 1 — wrong player name field in history:**
`p.get("name", "")` → `p.get("player_name", "")` in the history table cell and the game detail header cell.

**Bug 2 — history game detail card view shows no cards:**
`/history/games/{id}` returns only summary fields (no table/hands). The final state is available as the last row of `game_turns`, which is already fetched in the same notebook session. The card view cell should fall back to `game_turns[-1]` when `game_detail` lacks table/hand data (i.e., for history games).

---

### 3. Adjustable Bot Timeout

**game.py — `Game` class:**
- Add `bot_timeout_seconds: float = 10.0`
- Include in `to_dict()` / `from_dict()`

**main.py — new WebSocket message `set_bot_timeout`:**
```
{ "type": "set_bot_timeout", "seconds": <float> }
```
- Only the human (non-bot) player in the game may send this
- `seconds` clamped to `[2.0, 60.0]`
- Updates `game.bot_timeout_seconds` in place
- No broadcast needed (setting is server-side only)

**main.py — `trigger_bot_if_needed`:**
- Replace hardcoded `timeout=10.0` with `timeout=game.bot_timeout_seconds`

---

### 4. Bot Pre-computation During Opponent's Turn

**New module-level dict in main.py:**
```python
_bot_precomp: Dict[str, Future] = {}  # game_id -> submitted cf.Future
```

**After each human draw/play** (in WebSocket handler, after `broadcast_game_state`):
- If the next current player is a bot, immediately submit `find_best_play` to `_bot_pool` and store the future in `_bot_precomp[game_id]`
- This is fire-and-forget; any exception is logged and ignored

**In `trigger_bot_if_needed`** — before submitting a new job:
1. Compute current `state_key = (hand_key, table_key)` as today
2. Check `_bot_precomp.get(game_id)`:
   - **Future done, no exception, table+hand unchanged** → use result immediately; no pool submission; budget timer never started → effectively free
   - **Future done, table/hand changed** → discard result; run fresh job with full `bot_timeout_seconds` budget
   - **Future still running** → wrap it with `asyncio.wait_for(..., timeout=bot_timeout_seconds)`; budget starts now (at bot turn start), not at precomp start
   - **No precomp entry** → run fresh job as today
3. Pop `_bot_precomp[game_id]` after use (or if not used)

**Key invariant:** The bot's time budget (`bot_timeout_seconds`) is measured from when `trigger_bot_if_needed` starts, never from when pre-computation started.

**Cleanup:** Pop `_bot_precomp[game_id]` in `cleanup_ended_game` and `abort_game`.

---

### 5. Timeout Tracking in game_turns

**In `trigger_bot_if_needed`**, when `asyncio.TimeoutError` is caught:
- Call `record_turn(game, current['name'], "timeout_draw")` instead of `"draw"`

No schema changes needed — `action` is a free-text field.

---

## Files Changed

| File | Change |
|------|--------|
| `fly.toml` | Add `[[mounts]]` section |
| `game.py` | Add `bot_timeout_seconds` field |
| `main.py` | `set_bot_timeout` message handler; `_bot_precomp` dict; pre-computation in human turn handlers; timeout tracking; cleanup on game end/abort |
| `inspect_server.py` | Fix `player_name` field; history card view fallback to last turn |

---

## Out of Scope

- Migrating existing production data
- Fixing the v2 bot hang on complex game states (separate investigation)
- Exposing `bot_timeout_seconds` in the lobby UI
