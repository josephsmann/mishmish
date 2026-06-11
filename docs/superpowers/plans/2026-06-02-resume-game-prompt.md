# Resume-Game Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a fresh page load/login with a game still open, show a "Game in progress" card (opponent, status, last activity) with Rejoin / Abandon buttons instead of silently dropping the player into the game view.

**Architecture:** Pure client-side gate in `static/app.js` plus one server field. The server already restores sessions via `hello` → `hello_result {restored:true}` → `game_state` push; we add `last_activity` to the per-player state payload and gate the client's view switch on an in-memory `enteredGame` flag (fresh load = flag unset = show card; mid-game socket reconnect = flag set = silent restore). Abandon reuses the existing `abort_game` message verbatim.

**Tech Stack:** FastAPI/Python (server), vanilla JS + HTML/CSS (client), pytest via `uv run pytest`.

Spec: `docs/superpowers/specs/2026-06-02-resume-game-prompt-design.md`

**Note:** `Game.last_activity` already exists in `game.py` (updated in `start`, `draw_card`, `play_turn`, and included in `to_dict()`). The only server gap is that `state_for_player()` — the payload clients actually receive — omits it.

---

### Task 1: Expose `last_activity` in `state_for_player()`

**Files:**
- Modify: `game.py` (the `state_for_player` method, ~line 182–207)
- Test: `tests/test_game.py` (append new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game.py`:

```python
def _make_started_game():
    g = Game("g1", "p1")
    g.add_player("p1", "Alice")
    g.add_player("p2", "Bob")
    assert g.start("p1")
    return g


def test_state_for_player_includes_last_activity():
    g = _make_started_game()
    state = g.state_for_player("p1")
    assert state["last_activity"] == g.last_activity
    assert isinstance(state["last_activity"], str)


def test_last_activity_updates_on_draw():
    g = _make_started_game()
    before = g.last_activity
    import time
    time.sleep(0.01)
    current = g._get_current_player()["id"]
    g.draw_card(current)
    assert g.state_for_player("p1")["last_activity"] > before
```

(If `tests/test_game.py` does not already import `Game`, add `from game import Game` at the top.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_game.py -k last_activity -v`
Expected: 2 failures, `KeyError: 'last_activity'`.

- [ ] **Step 3: Implement**

In `game.py`, inside the dict returned by `state_for_player()`, add one line after `"bot_timeout_seconds": self.bot_timeout_seconds,`:

```python
            "last_activity": self.last_activity,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_game.py -v`
Expected: all PASS (including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add game.py tests/test_game.py
git commit -m "feat: expose last_activity in per-player game state"
```

---

### Task 2: Resume card markup and styles

**Files:**
- Modify: `static/index.html` (inside `<div id="view-lobby">`, directly after the `identity-bar` div, ~line 105)
- Modify: `static/style.css` (append)

No JS yet — the card stays `display:none` until Task 3 wires it.

- [ ] **Step 1: Add markup**

In `static/index.html`, inside `#view-lobby`'s `.lobby-container`, insert between the identity bar `</div>` and `<div class="lobby-actions">`:

```html
      <!-- Resume-game card: shown when the player has an open game on fresh load -->
      <div id="resume-card" style="display:none">
        <h2>Game in progress</h2>
        <p id="resume-opponent"></p>
        <p id="resume-meta"></p>
        <div class="resume-actions">
          <button id="btn-resume-rejoin" onclick="resumeRejoin()">Rejoin</button>
          <button id="btn-resume-abandon" onclick="resumeAbandon()">Abandon game</button>
        </div>
      </div>
```

- [ ] **Step 2: Add styles**

Append to `static/style.css`:

```css
/* Resume-game card */
#resume-card {
  background: #263238;
  border: 1px solid #4caf50;
  border-radius: 8px;
  padding: 16px;
  margin: 12px 0;
  text-align: center;
}
#resume-card h2 {
  margin: 0 0 8px;
  color: #a5d6a7;
}
#resume-card p {
  margin: 4px 0;
  color: #cfd8dc;
}
.resume-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 12px;
}
#btn-resume-rejoin {
  background: #2e7d32;
  color: #fff;
}
#btn-resume-abandon {
  background: #607d8b;
  color: #fff;
}
```

- [ ] **Step 3: Visual sanity check**

Run: `uv run uvicorn main:app --reload`, open `http://localhost:8000`, confirm the lobby renders unchanged (card hidden). In devtools, set `document.getElementById("resume-card").style.display = "block"` and confirm it looks reasonable.

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css
git commit -m "feat: resume-game card markup and styles (hidden)"
```

---

### Task 3: Client gate logic — show card on fresh load, silent restore otherwise

**Files:**
- Modify: `static/app.js`

Current behavior to change: the `case "game_state":` handler (~line 131) always calls `showView("game")`/`showView("waiting")`. We gate that on a new in-memory flag.

- [ ] **Step 1: Add the flag and helpers**

Near the top of `static/app.js`, after `let inGame = false;` (line 7), add:

```js
let enteredGame = false; // true once this JS session has shown the game/waiting view
```

Add these functions near the other view helpers (e.g. after `showView`, ~line 198):

```js
// ---- Resume card ----
function timeAgo(iso) {
  if (!iso) return "";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function showResumeCard(state) {
  const opponents = state.players
    .filter(p => p.id !== playerId)
    .map(p => p.name)
    .join(", ");
  document.getElementById("resume-opponent").textContent =
    opponents ? `vs ${opponents}` : "Waiting for players";
  const bits = [];
  if (state.status === "playing") {
    bits.push(state.your_turn ? "Your turn" : `${state.current_player_name}'s turn`);
    const mine = state.players.find(p => p.id === playerId);
    if (mine) bits.push(`${mine.hand_size} cards in hand`);
  } else {
    bits.push("Not started yet");
  }
  if (state.last_activity) bits.push(`last played ${timeAgo(state.last_activity)}`);
  document.getElementById("resume-meta").textContent = bits.join(" · ");
  document.getElementById("resume-card").style.display = "block";
}

function hideResumeCard() {
  document.getElementById("resume-card").style.display = "none";
}

function resumeRejoin() {
  hideResumeCard();
  enteredGame = true;
  if (!serverState) return;
  if (serverState.status === "waiting") {
    showView("waiting");
    renderWaiting();
  } else {
    syncStaged();
    showView("game");
    renderGame();
  }
}

function resumeAbandon() {
  hideResumeCard();
  send({ type: "abort_game" });
}
```

- [ ] **Step 2: Gate the `game_state` handler**

In `case "game_state":` the view-switching block currently reads:

```js
      if (serverState.status === "ended") {
        // Keep board visible; overlay the winner banner on top
        hideAbortConfirm();
        syncStaged();
        showView("game");
        renderGame();
        renderWinnerOverlay();
      } else if (serverState.status === "playing") {
        hideWinnerOverlay();
        syncStaged();
        showView("game");
        renderGame();
      } else {
        // waiting
        showView("waiting");
        renderWaiting();
      }
      break;
```

Replace with:

```js
      if (!enteredGame && serverState.status !== "ended") {
        // Fresh page load with a restored game: offer the choice instead of
        // dropping straight into the game (spec: resume-game prompt).
        showView("lobby");
        renderIdentityBar();
        showResumeCard(serverState);
        break;
      }
      if (serverState.status === "ended") {
        if (!enteredGame) {
          // Game finished before the player ever entered this session —
          // nothing to resume, just show the lobby.
          hideResumeCard();
          inGame = false;
          showView("lobby");
          break;
        }
        // Keep board visible; overlay the winner banner on top
        hideAbortConfirm();
        syncStaged();
        showView("game");
        renderGame();
        renderWinnerOverlay();
      } else if (serverState.status === "playing") {
        hideWinnerOverlay();
        syncStaged();
        showView("game");
        renderGame();
      } else {
        // waiting
        showView("waiting");
        renderWaiting();
      }
      break;
```

Note: repeated `game_state` pushes while the card is visible re-run
`showResumeCard(serverState)`, keeping it current (e.g. bot finishes its
turn).

- [ ] **Step 3: Set the flag on normal entry paths**

In `case "joined_game":` (line ~109), after `inGame = true;` add:

```js
      enteredGame = true;
```

(This covers create_game, join_game, and Play-vs-Bot — all flow through
`joined_game` — so newly created games never see the card.)

- [ ] **Step 4: Clear flag and card on game end paths**

In `case "game_aborted":` (line ~172), after `inGame = false;` add:

```js
      enteredGame = false;
      hideResumeCard();
```

Find the existing post-game "return to lobby" handler (~line 1017, the block
that sets `inGame = false;` then `showView("lobby")`) and add
`enteredGame = false;` beside `inGame = false;` there too.

In `signOut()` (~line 334, the block with `inGame = false;` before
`showView("auth")`), add `enteredGame = false;` and `hideResumeCard();`.

- [ ] **Step 5: Run existing test suite (regression)**

Run: `uv run pytest -v`
Expected: all PASS (no server behavior changed in this task).

- [ ] **Step 6: Commit**

```bash
git add static/app.js
git commit -m "feat: resume-game prompt on fresh load instead of silent restore"
```

---

### Task 4: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Start the server**

Run: `uv run uvicorn main:app --reload --port 8000`

- [ ] **Step 2: Fresh-load prompt appears**

1. Open `http://localhost:8000`, continue as guest, click **Play vs Bot**.
2. Play or draw one turn so the game is clearly in progress.
3. Reload the page (Cmd-R).
4. Expected: lobby view with the **Game in progress** card — "vs Mish Bot",
   turn info, hand count, "last played just now". NOT the game board.

- [ ] **Step 3: Rejoin works**

Click **Rejoin**. Expected: game board appears with correct table/hand;
playing a turn works.

- [ ] **Step 4: Abandon works**

Reload again (card reappears). Click **Abandon game**. Expected: card
disappears, lobby shows, no error banner (self-abort), and **Play vs Bot**
starts a brand-new game without an "Already in a game" error.

- [ ] **Step 5: Mid-game reconnect stays silent**

1. Start a new bot game, stay on the game view.
2. In devtools console run `ws.close()` to simulate a network blip.
3. Expected: after ~2s auto-reconnect, the game view re-renders directly.
   No resume card.

- [ ] **Step 6: Two-human abandon notifies opponent**

1. Window A (normal): create game. Window B (private/incognito): join it;
   creator starts the game.
2. Reload window A → card appears → click **Abandon game**.
3. Expected: window B gets the "Game was aborted" banner and returns to
   lobby.

- [ ] **Step 7: Commit any fixes found, then done**

If verification exposed bugs, fix and commit them with messages like
`fix: <issue>`. Final state: `uv run pytest -v` all green.
