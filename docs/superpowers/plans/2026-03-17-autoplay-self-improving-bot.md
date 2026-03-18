# Autoplay: Self-Improving Bot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local hill-climbing harness that runs bot-vs-bot games in-process to automatically find better bot parameters, while adding a greedy fallback to `bot.py` that eliminates the timeout pathology.

**Architecture:** Three pieces added to the existing codebase: (1) `BotConfig` dataclass and `_find_best_play_v3` in `bot.py` — same as v2 but switches to a fast greedy fallback when hand size exceeds a cutoff; (2) `bot_sim.py` — runs a complete Mishmish game in-process using `Game` directly, no server needed; (3) `autoplay.py` — hill-climbing loop that mutates bot configs, runs 50-game matchups, promotes winners, logs everything.

**Tech Stack:** Python 3.12, `dataclasses`, `game.py` / `bot.py` (existing), `uv run python autoplay.py` to run.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `bot.py` | Modify | Add `BotConfig` dataclass, `_find_best_play_v3`, update `find_best_play` dispatcher |
| `bot_sim.py` | Create | In-process game simulator: `simulate_game(a, b) -> str` |
| `autoplay.py` | Create | Hill-climbing harness: mutate → tournament → log → repeat |
| `tests/test_bot_v3.py` | Create | Tests for v3 greedy fallback and BotConfig |
| `tests/test_bot_sim.py` | Create | Tests for simulate_game |

---

## Task 1: Add `BotConfig` and update dispatcher in `bot.py`

**Files:**
- Modify: `bot.py` (add dataclass near top, update `find_best_play` at bottom)
- Test: `tests/test_bot_v3.py`

- [ ] **Step 1: Write the failing test for BotConfig**

```python
# tests/test_bot_v3.py
import pytest
from bot import BotConfig, find_best_play


def test_botconfig_defaults():
    cfg = BotConfig()
    assert cfg.lam == 0.5
    assert cfg.hand_cutoff == 10


def test_botconfig_custom():
    cfg = BotConfig(lam=0.8, hand_cutoff=12)
    assert cfg.lam == 0.8
    assert cfg.hand_cutoff == 12


def test_find_best_play_accepts_config_kwarg():
    """find_best_play must not crash when config is passed."""
    hand = [{"rank": "A", "suit": "S"}, {"rank": "A", "suit": "H"}, {"rank": "A", "suit": "D"}]
    cfg = BotConfig()
    result = find_best_play(hand, [], version="v3", config=cfg)
    # Should return a table with the triple
    assert result is not None
    assert len(result) == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_bot_v3.py -v
```
Expected: `ImportError` or `TypeError` — `BotConfig` doesn't exist yet.

- [ ] **Step 3: Add `BotConfig` to `bot.py`**

Add after the existing imports at the top of `bot.py` (after line 4, before line 6):

```python
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    lam: float = 0.5
    hand_cutoff: int = 10
```

- [ ] **Step 4: Update `find_best_play` dispatcher to accept and forward `config`**

The current dispatcher at the bottom of `bot.py` looks like:
```python
def find_best_play(hand, table, version=DEFAULT):
    fn = VERSIONS.get(version) or VERSIONS[DEFAULT]
    ...
```

Replace it with:
```python
def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
    version: str = DEFAULT,
    config: "BotConfig | None" = None,
) -> Optional[List[List[Card]]]:
    """Dispatch to the requested bot version. Falls back to DEFAULT if unknown."""
    fn = VERSIONS.get(version) or VERSIONS[DEFAULT]
    if version == "v3" or (version not in VERSIONS and DEFAULT == "v3"):
        cfg = config or BotConfig()
        return fn(hand, table, config=cfg)
    return fn(hand, table)
```

- [ ] **Step 5: Run tests — expect partial pass (BotConfig tests pass, v3 test fails)**

```bash
uv run pytest tests/test_bot_v3.py -v
```
Expected: first two tests PASS, `test_find_best_play_accepts_config_kwarg` FAIL with `KeyError` or similar — v3 not in VERSIONS yet.

- [ ] **Step 6: Commit checkpoint**

```bash
git add bot.py tests/test_bot_v3.py
git commit -m "feat: add BotConfig dataclass and config kwarg to find_best_play dispatcher"
```

---

## Task 2: Implement `_find_best_play_v3` in `bot.py`

**Files:**
- Modify: `bot.py` (add `_find_best_play_v3`, add to VERSIONS)
- Test: `tests/test_bot_v3.py`

- [ ] **Step 1: Write tests for v3 greedy fallback behaviour**

Add to `tests/test_bot_v3.py`:

```python
def c(rank, suit):
    return {"rank": rank, "suit": suit}


def test_v3_below_cutoff_uses_full_backtracking():
    """With a small hand (≤ cutoff), v3 should find the same result as v2."""
    hand = [c("A","S"), c("A","H"), c("A","D")]
    cfg = BotConfig(hand_cutoff=10)  # hand size 3 < 10 → full backtracking
    result_v2 = find_best_play(hand, [], version="v2")
    result_v3 = find_best_play(hand, [], version="v3", config=cfg)
    # Both should play the triple
    assert result_v3 is not None
    assert len(result_v3) == 1
    assert len(result_v3[0]) == 3


def test_v3_above_cutoff_uses_greedy_fallback():
    """With a large hand (> cutoff), v3 must still return a valid play."""
    # 11 cards: a valid triple + filler
    hand = [
        c("A","S"), c("A","H"), c("A","D"),  # valid triple
        c("2","S"), c("3","H"), c("4","D"), c("5","C"),
        c("7","S"), c("8","H"), c("9","D"), c("10","C"),
    ]
    cfg = BotConfig(lam=0.5, hand_cutoff=5)  # hand size 11 > 5 → greedy
    result = find_best_play(hand, [], version="v3", config=cfg)
    # Should play at least the triple
    assert result is not None
    assert len(result) >= 1


def test_v3_returns_none_when_no_valid_play():
    """With a large hand and no valid melds, v3 returns None."""
    hand = [c("2","S"), c("4","H"), c("7","D"), c("J","C"),
            c("3","S"), c("9","H"), c("K","D"), c("5","C"),
            c("6","S"), c("8","H"), c("Q","D")]
    cfg = BotConfig(lam=0.5, hand_cutoff=5)  # greedy path
    result = find_best_play(hand, [], version="v3", config=cfg)
    assert result is None


def test_v3_greedy_produces_valid_melds():
    """All melds returned by v3 greedy must be valid."""
    from deck import is_valid_meld
    hand = [
        c("5","S"), c("5","H"), c("5","D"), c("5","C"),
        c("6","S"), c("6","H"), c("6","D"),
        c("7","S"), c("7","H"), c("7","D"), c("7","C"),
    ]
    cfg = BotConfig(lam=0.0, hand_cutoff=5)  # greedy, no opportunity penalty
    result = find_best_play(hand, [], version="v3", config=cfg)
    assert result is not None
    for meld in result:
        assert is_valid_meld(meld), f"Invalid meld: {meld}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_bot_v3.py -v
```
Expected: all v3 tests FAIL — `_find_best_play_v3` not implemented yet.

- [ ] **Step 3: Implement `_find_best_play_v3`**

Add this function to `bot.py` just before the `# ── Version registry` section:

```python
# ── V3: v2 with greedy fallback for large hands ────────────────────────────


def _find_best_play_v3(
    hand: List[Card],
    table: List[List[Card]],
    config: "BotConfig | None" = None,
) -> Optional[List[List[Card]]]:
    """
    Like v2 but switches to a fast greedy fallback when len(hand) > config.hand_cutoff.

    Greedy fallback:
      1. Score each candidate meld that includes ≥1 hand card:
             score = cards_from_hand - lam * opportunities
         where opportunities = # candidates formable entirely from
         (table_cards + played_hand_cards) that include ≥1 played hand card.
      2. Pick the best-scoring single meld (return None if score ≤ 0).
      3. Append any additional hand-only melds via _pack_hand.
    """
    if config is None:
        config = BotConfig()

    if not hand:
        return None

    if len(hand) <= config.hand_cutoff:
        return _find_best_play_v2(hand, table, lam=config.lam)

    # ── Greedy path ────────────────────────────────────────────────────────
    table_cards = [card for meld in table for card in meld]
    n_table = len(table_cards)
    pool = table_cards + hand
    n_pool = len(pool)

    candidates = _build_candidates(pool)

    cand_masks: List[int] = []
    cand_cards_list: List[list] = []
    for indices, meld_cards in candidates:
        mask = 0
        for i in indices:
            mask |= 1 << i
        cand_masks.append(mask)
        cand_cards_list.append(meld_cards)

    hand_mask = ((1 << len(hand)) - 1) << n_table

    # All table cards must be covered; only consider candidates that also
    # cover every table card in the candidate's bit range.
    # For simplicity in the greedy path: find candidates that include ≥1 hand card.
    hand_candidates = [
        (cand_masks[ci], cand_cards_list[ci])
        for ci in range(len(candidates))
        if cand_masks[ci] & hand_mask  # includes ≥1 hand card
    ]

    if not hand_candidates:
        return None

    # We need to also cover all existing table cards. Filter to candidates
    # that are compatible with covering the full table (i.e., the candidate
    # covers all its own cards and doesn't remove table cards).
    # Build a "table_cover_mask" — all bits for table card positions.
    table_full_mask = (1 << n_table) - 1

    # For the greedy path, we try each hand-involving candidate as the primary
    # meld, paired with any remaining table-covering melds found via the
    # existing backtracker restricted to table cards only.
    # Simplified approach: only consider candidates that include ALL table cards
    # they share pool positions with — i.e., pick melds that don't require
    # a specific table arrangement we'd have to backtrack over.
    #
    # Actually: the greedy does a single-pass: score each candidate meld that
    # contains ≥1 hand card and covers its own table slots, pick the best, then
    # let _pack_hand cover remaining hand cards. For the table coverage
    # requirement, we run the same MRV-cover check as v2 but only to depth 1
    # (cover the table cards that appear in our chosen meld).
    #
    # Simpler valid approach used here:
    # - Require the candidate to not leave table cards uncovered.
    # - A candidate is "self-contained" for table coverage if all table card
    #   indices it uses are covered within itself (which they must be — each
    #   candidate is already a valid meld). But we still need to cover table
    #   cards NOT in this candidate.
    # - So: score only candidates where choosing that candidate + the existing
    #   table melds leaves no table card uncovered. This means the candidate
    #   must cover exactly the table cards it touches, and the remaining table
    #   cards are already covered by other (unchanged) table melds.
    #
    # Concrete rule: a hand-involving candidate is viable if every table-card
    # index in it is already covered by the table (i.e., it "extends" the table
    # rather than "rearranging" it) OR it covers all table cards entirely.
    # Since candidates from _build_candidates may span table+hand cards,
    # the simplest correct rule: only score candidates whose table-card bits
    # form a subset of one existing meld's bits (we're adding to an existing
    # meld or forming a new all-hand meld).
    #
    # Pragmatic implementation: collect meld-index sets for current table melds.
    table_meld_masks = []
    offset = 0
    for meld in table:
        m = 0
        for i in range(len(meld)):
            m |= 1 << (offset + i)
        offset += len(meld)
        table_meld_masks.append(m)

    best_score = 0.0
    best_ci = -1

    for ci, (mask, cards) in enumerate(hand_candidates):
        table_bits_in_cand = mask & table_full_mask
        hand_bits_in_cand = mask & hand_mask

        # Only allow if the table-card portion of this candidate falls entirely
        # within a single existing table meld (extending it) or has no table bits.
        if table_bits_in_cand:
            fits = any((table_bits_in_cand & tm) == table_bits_in_cand
                       for tm in table_meld_masks)
            if not fits:
                continue

        cards_from_hand = bin(hand_bits_in_cand).count('1')

        # Compute opportunities: candidates formable from (table + played hand cards)
        # that include ≥1 of the played hand cards.
        final_covered = table_full_mask | hand_bits_in_cand
        opportunities = sum(
            1 for ci2 in range(len(cand_masks))
            if (cand_masks[ci2] & final_covered) == cand_masks[ci2]
            and cand_masks[ci2] & hand_bits_in_cand
        )

        score = cards_from_hand - config.lam * opportunities
        if score > best_score:
            best_score = score
            best_ci = ci

    if best_ci == -1:
        return None

    chosen_mask, chosen_cards = hand_candidates[best_ci]

    # Build new_table: existing table melds + the chosen meld
    # (which may extend an existing meld or be a new all-hand meld).
    table_bits_in_chosen = chosen_mask & table_full_mask
    hand_bits_in_chosen = chosen_mask & hand_mask

    if table_bits_in_chosen:
        # Extending an existing table meld: rebuild table replacing that meld.
        new_table = []
        offset = 0
        extended = False
        for meld in table:
            meld_mask = 0
            for i in range(len(meld)):
                meld_mask |= 1 << (offset + i)
            offset += len(meld)
            if not extended and (table_bits_in_chosen & meld_mask) == table_bits_in_chosen:
                new_table.append(chosen_cards)
                extended = True
            else:
                new_table.append(meld)
    else:
        # New all-hand meld: keep existing table, append new meld.
        new_table = list(table) + [chosen_cards]

    # Pack remaining hand cards into additional melds.
    played_hand_indices = [i for i in range(n_table, n_pool)
                           if (chosen_mask >> i) & 1]
    unused_hand_indices = [n_table + j for j in range(len(hand))
                           if not ((chosen_mask >> (n_table + j)) & 1)]
    _, extra_melds = _pack_hand(pool, unused_hand_indices, candidates)
    new_table.extend(extra_melds)

    return new_table
```

- [ ] **Step 4: Register v3 in VERSIONS**

In the `VERSIONS` dict at the bottom of `bot.py`, add the v3 entry:

```python
VERSIONS: dict = {
    "v1": _find_best_play_v1,
    "v2": _find_best_play_v2,
    "v3": _find_best_play_v3,
}
```

- [ ] **Step 5: Run all v3 tests**

```bash
uv run pytest tests/test_bot_v3.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
uv run pytest -v
```
Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add bot.py tests/test_bot_v3.py
git commit -m "feat: add bot v3 with greedy fallback for large hands"
```

---

## Task 3: Build `bot_sim.py` — in-process game simulator

**Files:**
- Create: `bot_sim.py`
- Test: `tests/test_bot_sim.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_bot_sim.py
import pytest
from bot import BotConfig
from bot_sim import simulate_game


def test_simulate_game_returns_valid_outcome():
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    result = simulate_game(cfg, cfg)
    assert result in ("a", "b", "draw")


def test_simulate_game_completes_without_hanging():
    """Game must complete within a reasonable time (no infinite loops)."""
    import time
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    start = time.time()
    simulate_game(cfg, cfg)
    elapsed = time.time() - start
    assert elapsed < 10.0, f"Game took too long: {elapsed:.1f}s"


def test_simulate_game_symmetric():
    """Running many games should not always return the same winner (non-degenerate)."""
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    results = [simulate_game(cfg, cfg) for _ in range(20)]
    # Not all the same result
    assert len(set(results)) > 1


def test_simulate_game_different_configs():
    """Two configs can be compared — just check it runs cleanly."""
    cfg_a = BotConfig(lam=0.0, hand_cutoff=6)
    cfg_b = BotConfig(lam=1.0, hand_cutoff=14)
    result = simulate_game(cfg_a, cfg_b)
    assert result in ("a", "b", "draw")


def test_simulate_game_draw_on_deck_exhaustion(monkeypatch):
    """simulate_game returns 'draw' when the deck runs out."""
    from unittest.mock import patch
    import game as game_module

    original_make_deck = game_module.make_deck

    def tiny_deck():
        # Return just enough cards to deal 9 each (18 cards) but nothing left to draw
        return original_make_deck()[:18]

    with patch.object(game_module, "make_deck", tiny_deck):
        cfg = BotConfig(lam=0.5, hand_cutoff=10)
        result = simulate_game(cfg, cfg)
        assert result == "draw"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_bot_sim.py -v
```
Expected: `ImportError` — `bot_sim` doesn't exist yet.

- [ ] **Step 3: Implement `bot_sim.py`**

```python
"""
bot_sim.py — In-process Mishmish game simulator for bot tournament use.

simulate_game(config_a, config_b) -> "a" | "b" | "draw"

Runs a complete game between two bot configs using Game directly.
No HTTP, WebSocket, or ProcessPoolExecutor involved.
"""
import uuid
from typing import Literal

from bot import BotConfig, _find_best_play_v3
from game import Game

TURN_CAP = 500


def simulate_game(
    config_a: BotConfig,
    config_b: BotConfig,
) -> Literal["a", "b", "draw"]:
    """
    Play one complete game between config_a (player index 0 = non-dealer,
    goes first) and config_b (player index 1 = dealer).

    Returns "a" if config_a's bot wins, "b" if config_b's bot wins,
    "draw" if the deck is exhausted or the turn cap is reached.
    """
    creator_id = "sim_" + uuid.uuid4().hex[:8]
    bot_a_id = "bot_a_" + uuid.uuid4().hex[:6]
    bot_b_id = "bot_b_" + uuid.uuid4().hex[:6]

    game = Game(game_id=uuid.uuid4().hex[:8], creator_id=creator_id)
    # Add a dummy creator so start() works (creator must be a player or
    # we bypass by making one of the bots the creator).
    # Simplest: make bot_a the creator.
    game.creator_id = bot_a_id
    game.add_player(bot_a_id, "Bot A", is_bot=True)
    game.add_player(bot_b_id, "Bot B", is_bot=True)
    game.start(requestor_id=bot_a_id)

    config_map = {bot_a_id: config_a, bot_b_id: config_b}
    id_to_key = {bot_a_id: "a", bot_b_id: "b"}

    for _ in range(TURN_CAP):
        if game.status == "ended":
            break

        current = game._get_current_player()
        if current is None:
            break

        pid = current["id"]
        hand = current["hand"]
        config = config_map[pid]

        new_table = _find_best_play_v3(hand, game.table, config=config)

        if new_table is not None:
            ok, msg = game.play_turn(pid, new_table)
            if not ok:
                # v3 produced an invalid table — fall back to drawing
                game.draw_card(pid)
        else:
            game.draw_card(pid)
            # draw_card may end the game on deck exhaustion

        if game.status == "ended":
            break

    if game.status != "ended":
        return "draw"

    if game.winner_id is None:
        return "draw"

    return id_to_key.get(game.winner_id, "draw")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_bot_sim.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add bot_sim.py tests/test_bot_sim.py
git commit -m "feat: add bot_sim in-process game simulator"
```

---

## Task 4: Build `autoplay.py` — hill-climbing harness

**Files:**
- Create: `autoplay.py`

No automated tests for the harness itself — it's a script. Verify manually by running a short session.

- [ ] **Step 1: Implement `autoplay.py`**

```python
"""
autoplay.py — Hill-climbing bot tournament harness.

Run with: uv run python autoplay.py

Mutates BotConfig parameters one at a time, runs 50-game matchups between
champion and challenger, promotes challenger if win rate > 55%.
Logs results to autoplay_log.jsonl and prints live progress.

Stop with Ctrl+C — champion config is printed on exit.
"""
import json
import random
import signal
import sys
import time
from dataclasses import asdict

from bot import BotConfig
from bot_sim import simulate_game

# ── Tournament parameters ───────────────────────────────────────────────────
GAMES_PER_MATCHUP = 50
WIN_THRESHOLD = 0.55        # challenger must exceed this to be promoted
LOG_FILE = "autoplay_log.jsonl"

# ── Mutation bounds ─────────────────────────────────────────────────────────
LAM_SIGMA = 0.1
LAM_MIN, LAM_MAX = 0.0, 2.0
CUTOFF_DELTA_CHOICES = [-2, -1, 1, 2]
CUTOFF_MIN, CUTOFF_MAX = 6, 20


def mutate(config: BotConfig) -> BotConfig:
    """Return a new BotConfig with one parameter perturbed."""
    if random.random() < 0.5:
        new_lam = config.lam + random.gauss(0, LAM_SIGMA)
        new_lam = max(LAM_MIN, min(LAM_MAX, new_lam))
        return BotConfig(lam=round(new_lam, 4), hand_cutoff=config.hand_cutoff)
    else:
        delta = random.choice(CUTOFF_DELTA_CHOICES)
        new_cutoff = max(CUTOFF_MIN, min(CUTOFF_MAX, config.hand_cutoff + delta))
        return BotConfig(lam=config.lam, hand_cutoff=new_cutoff)


def run_matchup(config_a: BotConfig, config_b: BotConfig) -> dict:
    """
    Play GAMES_PER_MATCHUP games, alternating who goes first.
    Returns dict with a_wins, b_wins, draws.
    """
    a_wins = b_wins = draws = 0
    half = GAMES_PER_MATCHUP // 2

    # First half: A goes first
    for _ in range(half):
        result = simulate_game(config_a, config_b)
        if result == "a":
            a_wins += 1
        elif result == "b":
            b_wins += 1
        else:
            draws += 1

    # Second half: B goes first
    for _ in range(GAMES_PER_MATCHUP - half):
        result = simulate_game(config_b, config_a)
        if result == "b":
            a_wins += 1   # B-first means swapped: b_first win = original a
        elif result == "a":
            b_wins += 1
        else:
            draws += 1

    return {"a_wins": a_wins, "b_wins": b_wins, "draws": draws}


def fmt_config(cfg: BotConfig) -> str:
    return f"lam={cfg.lam:.4f} cutoff={cfg.hand_cutoff}"


def main():
    champion = BotConfig(lam=0.5, hand_cutoff=10)
    start_time = time.time()
    round_num = 0

    def on_exit(sig=None, frame=None):
        elapsed = time.time() - start_time
        print(f"\n\nStopped after {round_num} rounds ({elapsed:.0f}s)")
        print(f"Final champion: {fmt_config(champion)}")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)

    print(f"Starting hill-climbing tournament")
    print(f"Champion: {fmt_config(champion)}")
    print(f"Games/matchup: {GAMES_PER_MATCHUP} | Win threshold: {WIN_THRESHOLD:.0%}\n")

    with open(LOG_FILE, "a") as log:
        while True:
            round_num += 1
            challenger = mutate(champion)
            pre_round_champion = champion  # snapshot before any promotion

            print(f"Round {round_num} | Champion: {fmt_config(champion)} | "
                  f"Challenger: {fmt_config(challenger)}")

            matchup_start = time.time()
            result = run_matchup(champion, challenger)
            matchup_elapsed = time.time() - matchup_start

            a_wins = result["a_wins"]
            b_wins = result["b_wins"]
            draws = result["draws"]
            total_decisive = a_wins + b_wins
            challenger_rate = b_wins / total_decisive if total_decisive > 0 else 0.0
            promoted = challenger_rate > WIN_THRESHOLD

            if promoted:
                champion = challenger
                tag = " ← NEW CHAMPION"
            else:
                tag = ""

            print(f"  Games: {GAMES_PER_MATCHUP} | Champion wins: {a_wins} | "
                  f"Challenger wins: {b_wins} ({challenger_rate:.0%}){tag}")
            print(f"  Draws: {draws} | Matchup time: {matchup_elapsed:.1f}s | "
                  f"Total elapsed: {time.time()-start_time:.0f}s\n")

            entry = {
                "round": round_num,
                "champion": asdict(pre_round_champion),
                "challenger": asdict(challenger),
                "champion_wins": a_wins,
                "challenger_wins": b_wins,
                "draws": draws,
                "promoted": promoted,
                "elapsed_s": round(time.time() - start_time),
            }
            log.write(json.dumps(entry) + "\n")
            log.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run a short smoke test (5 rounds)**

```bash
uv run python autoplay.py
```

Watch for 5 rounds of output like:
```
Round 1 | Champion: lam=0.5000 cutoff=10 | Challenger: lam=0.4731 cutoff=10
  Games: 50 | Champion wins: 26 | Challenger wins: 24 (48%)
  Draws: 0 | Matchup time: 3.2s | Total elapsed: 3s
```

Stop with Ctrl+C after 5 rounds. Check `autoplay_log.jsonl` has 5 JSON lines.

```bash
wc -l autoplay_log.jsonl
head -1 autoplay_log.jsonl | python3 -m json.tool
```

Expected: 5 lines, valid JSON.

- [ ] **Step 3: Clean up log and commit**

```bash
rm autoplay_log.jsonl
git add autoplay.py
git commit -m "feat: add autoplay hill-climbing bot tournament harness"
```

---

## Task 5: Final integration check

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS.

- [ ] **Step 2: Verify v3 is wire-compatible with the game server**

The server currently dispatches bot turns using `find_best_play(hand, table, version=bot_version)`. Since v3 requires a `config` kwarg and we updated the dispatcher to handle it, verify with:

```bash
uv run python -c "
from bot import find_best_play, BotConfig
hand = [{'rank':'A','suit':'S'},{'rank':'A','suit':'H'},{'rank':'A','suit':'D'}]
# Without config — should use BotConfig defaults
result = find_best_play(hand, [], version='v3')
print('v3 without config:', result)
# With config
result2 = find_best_play(hand, [], version='v3', config=BotConfig(lam=0.3, hand_cutoff=8))
print('v3 with config:', result2)
"
```
Expected: both return a table with one 3-card meld.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: autoplay tournament harness complete (v3 bot + bot_sim + autoplay)"
```

---

## Running overnight

```bash
uv run python autoplay.py
```

Let it run. In the morning, check the best config:

```bash
python3 -c "
import json
lines = [json.loads(l) for l in open('autoplay_log.jsonl')]
promotions = [l for l in lines if l['promoted']]
if promotions:
    last = promotions[-1]
    print(f'Best found: lam={last[\"challenger\"][\"lam\"]} cutoff={last[\"challenger\"][\"hand_cutoff\"]}')
    print(f'After {len(lines)} rounds')
else:
    print('No improvements found yet — starting config may already be good')
"
```

To promote the winner to production default, update `bot.py`:
```python
DEFAULT = "v3"
```
And set the winning config as `BotConfig` defaults.
