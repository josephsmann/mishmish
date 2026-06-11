# Resume-Game Prompt — Design

Date: 2026-06-02
Status: Approved

## Problem

When a logged-in (or guest) player returns to Mishmish with a game still in
progress, the client silently drops them back into the game view. Players who
got disconnected hours earlier (e.g. browser navigated away mid-game) land in
a stale game with no context and no way to opt out other than the in-game
abort button. There is no visibility of the open session at login time.

## Scope decisions

- **One game per player stays.** The server's `player_games` (one slot per
  player) is unchanged. This feature surfaces the single open game; it does
  not add multi-game support.
- **Decline path = abandon.** Declining the prompt aborts the game via the
  existing `abort_game` flow (opponent notified, game recorded as aborted).
- **Prompt on fresh load only.** Mid-game socket reconnects (Wi-Fi blips, iOS
  focus loss) silently restore as today. Only a fresh page load / new login
  shows the prompt.

## Approach

Client-side gate (Approach A). The server already sends everything needed at
`hello` time: `hello_result {restored: true}` followed by a `game_state`
push. No new protocol messages.

### Client (`static/app.js`)

- New in-memory flag `wasInGameThisSession` (plain JS variable, NOT
  sessionStorage). Set when entering the game view; cleared on game end /
  abort. Because it is in-memory, any reload or new tab loses it (→ prompt),
  while mid-game socket reconnects keep it (→ silent restore).
- On `hello_result {restored: true}` + first `game_state`:
  - If `wasInGameThisSession` → enter game view directly (today's behavior).
  - Else → render a **resume card** over the lobby view.
- Resume card shows: opponent name(s) (from `state.players` minus self),
  status (`waiting`/`playing`), whose turn, own hand size, and relative
  "last played X ago" from `state.last_activity`.
- Buttons:
  - **Rejoin** → `showView("game")`, set the flag.
  - **Abandon** → send `{type: "abort_game"}`; on `game_aborted
    {reason: "self"}` show the lobby. Opponent receives the existing
    `game_aborted {reason: "other"}`.

### Server (`game.py` / `main.py`)

- Add `last_activity` (UTC ISO timestamp) to the game, updated on every
  successful `draw_card` / `play_turn` (and on game start). Include it in
  `Game.to_dict()`.
- No other server changes; `abort_game` is reused verbatim.

### Guests

Identical behavior — the `saved_player_id` restore path emits the same
`hello_result`/`game_state` sequence.

## Error handling

- If the game ends/aborts between page load and the player's choice, the
  incoming `game_state`/`game_aborted` message dismisses the card and shows
  the lobby.
- `abort_game` failure (e.g. game already gone) returns an error message;
  client falls back to showing the lobby.

## Testing

- Unit: `Game.to_dict()` includes `last_activity`; it updates on
  `draw_card`/`play_turn`.
- Manual flow: start game → reload page → card appears with correct opponent
  and timestamp; Rejoin enters game; Abandon aborts and notifies opponent;
  mid-game network toggle → no card, silent restore.
