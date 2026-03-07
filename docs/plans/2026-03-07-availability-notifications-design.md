# Availability Notifications Design

**Date**: 2026-03-07
**Status**: Approved

## Summary

Users with registered phone numbers can mark themselves as "available to play" and notify a selected subset of other registered users via SMS. Notified users receive a deep link to join them in the lobby.

## Approach

Pure SMS with server-side availability state (no WebSocket presence). The server tracks availability, sends SMS on activation, and auto-clears on expiry or game join. Phone numbers are never exposed to other users.

## Data Model

### New table: `user_availability`
Tracks active availability sessions. One row per user; upsert on each activation.

| Column | Type | Notes |
|--------|------|-------|
| `user_id` | TEXT | FK to users |
| `available_until` | TIMESTAMP | Expiry time |
| `created_at` | TIMESTAMP | |

### New table: `notify_list_defaults`
Persists the last-chosen recipient list per user.

| Column | Type | Notes |
|--------|------|-------|
| `user_id` | TEXT | FK to users |
| `recipient_ids` | JSON | Array of user IDs, or `["all"]` |

## API Endpoints

### `POST /availability`
Activate availability. Requires JWT auth.

**Body:**
```json
{
  "timeout_minutes": 30,
  "notify": ["all"] | ["user_id_1", "user_id_2"]
}
```

- Saves `available_until = now + timeout_minutes`
- Saves `notify_list_defaults` for next session
- Fires SMS to selected recipients (skips users without phone numbers)
- Returns `400` if caller has no phone number or is currently in a game

### `DELETE /availability`
Manually deactivate. Requires JWT auth.

### `GET /users`
Returns all registered users with phone numbers: `id` + display name only. Used to populate the recipient picker UI. Requires JWT auth.

## Auto-Clear Triggers

1. **Game join/create**: clear `user_availability` row when user joins or creates a game (in WebSocket handler in `main.py`)
2. **Expiry background task**: `asyncio` loop runs periodically (e.g., every 5 minutes), deletes rows where `available_until < now`

## SMS

Reuses existing Twilio client from `auth.py`. New helper `send_availability_sms(to_number, from_username)` in `auth.py` or a new `sms.py`.

**Message format:**
> [Username] is ready to play Mish Mish! Join them: https://mishmish-game.fly.dev?ready=[username]

**Deep link handling (client-side):** `?ready=username` param shows a prompt to join a game with that user. If the recipient is already in a game, the param is ignored and the lobby opens normally.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Caller has no phone number | `400` — "Add a phone number to use this feature" |
| Recipient has no phone number | Silently skipped |
| Caller already in a game | `400` — "You're already in a game" |
| Already available | Upsert — resets timer, re-sends SMS |
| Twilio failure | Log error, don't fail request — availability still set |
| Deep link recipient already in game | Frontend ignores `?ready=` param, shows lobby |

## Testing

- Unit tests: `available_until` expiry logic, auto-clear on game join
- Integration tests: `POST /availability`, `DELETE /availability` via `TestClient`
- Twilio mocked in all tests — no real SMS sent
- Test recipient expansion: "all" → users with phone numbers only
- Test `notify_list_defaults` save/load round-trip
