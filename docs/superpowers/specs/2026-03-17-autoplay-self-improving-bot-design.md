# Autoplay: Self-Improving Bot via Hill-Climbing Tournament

**Date:** 2026-03-17
**Status:** Approved

## Problem

The v2 bot times out consistently when `hand_size` is large (>~7 cards) AND the table has many melds (>~13). Each timeout burns the full CPU budget before being killed. In bad games, this produces 10+ consecutive timeouts, pegging a CPU core for minutes.

The root cause: the exact-cover backtracker's search space grows with both hand size and table size simultaneously. No existing code limits either.

## Goal

Build a local, overnight-runnable harness that:
1. Finds better bot parameters automatically via hill-climbing self-play
2. Organically solves the timeout problem (bots that timeout lose → get discarded)
3. Produces a new `v3` bot config that replaces `v2` as the default

---

## New Files

### `bot_sim.py` — In-process game simulator

```
simulate_game(config_a: BotConfig, config_b: BotConfig) -> str  # "a" | "b" | "draw"
```

- Creates a `Game` instance directly (no HTTP, no WebSocket, no ProcessPoolExecutor)
- Uses the creator's player ID as `requestor_id` when calling `game.start()`
- On each turn: reads current player via `game._get_current_player()` to get `player_id`
- Calls `_find_best_play_v3(hand, table, config=config)` directly (bypasses dispatcher)
- If play returned → `game.play_turn(player_id, new_table)` where `new_table` = existing table cards + new meld(s); else → `game.draw_card(player_id)`
- Checks `game.status == "ended"` after every action (deck exhaustion ends game inside `draw_card`)
- Caps at 500 turns → returns "draw"
- No timeouts needed — v3's greedy fallback keeps every turn fast

### `autoplay.py` — Hill-climbing harness

Loop:
1. Mutate one parameter of current champion → challenger
2. Run 50 games (25 with A first, 25 with B first)
3. If challenger win rate > 55% → promote to champion
4. Log result, print progress, repeat

Runs until killed (Ctrl+C). Designed for overnight runs.

---

## Bot Config

```python
@dataclass
class BotConfig:
    lam: float        # opportunity penalty weight (v2 default: 0.5)
    hand_cutoff: int  # switch to greedy above this hand size (default: 10)
```

**Starting champion:** `lam=0.5, hand_cutoff=10`

`hand_cutoff=10` is intentionally aggressive — players start with 9 cards and quickly exceed 10 when drawing, so the fallback triggers regularly from early in the hill-climbing process. The tournament will naturally select higher cutoffs if full backtracking wins more.

**Mutation rules:**
- `lam`: sample from N(0, 0.1), clamp to [0.0, 2.0]
- `hand_cutoff`: ±1 or ±2 uniform, clamp to [6, 20]
- One parameter mutated per round

---

## Bot v3 (changes to `bot.py`)

New function `_find_best_play_v3(hand, table, config: BotConfig)`. Same as v2 with a `hand_cutoff` branch.

**When `len(hand) > config.hand_cutoff`** (greedy fallback):
1. Build `pool = table_cards + hand`; call `_build_candidates(pool)`
2. For each candidate meld that includes ≥1 hand card, score it:
   `cards_from_hand_in_meld - lam * opportunities`
   where `opportunities` = number of candidate melds formable entirely from
   `table_cards + played_hand_cards` that include ≥1 of the played hand cards
   (same definition as v2's opportunity count at the leaf node)
3. Pick best-scoring single meld; if score ≤ 0, return None (draw)
4. Build `new_table` = existing table melds + [chosen meld's cards]
5. Run `_pack_hand` on remaining hand cards, append any extra melds to `new_table`
6. Return `new_table`

**When `len(hand) <= config.hand_cutoff`**: full v2 exact-cover backtracking (unchanged).

The opportunity definition deliberately matches v2 so that `lam` values are comparable across the two regimes and hill-climbing produces a single coherent `lam`.

---

## Tournament Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Games per matchup | 50 | Low variance, ~2s per matchup at target speed |
| Win threshold | 55% (28/50) | Avoids noise-driven regressions |
| First-mover balance | 25 games each side | Eliminates first-player advantage |
| Turn cap | 500 | Prevents infinite games |

---

## Logging

**Terminal (live):**
```
Round 12 | Champion: lam=0.47 cutoff=11 | Challenger: lam=0.51 cutoff=11
  Games: 50 | Champion wins: 21 | Challenger wins: 29 (58%) ← NEW CHAMPION
  Best so far: lam=0.51 cutoff=11 | Rounds run: 12 | Elapsed: 4m32s
```

**`autoplay_log.jsonl` (one JSON line per round):**
```json
{
  "round": 12,
  "champion": {"lam": 0.47, "hand_cutoff": 11},
  "challenger": {"lam": 0.51, "hand_cutoff": 11},
  "champion_wins": 21,
  "challenger_wins": 29,
  "draws": 0,
  "promoted": true,
  "elapsed_s": 272
}
```

---

## Integration

After a satisfying champion is found:
1. Copy its config into `bot.py` as `v3` defaults
2. Set `DEFAULT = "v3"` in the version registry
3. Deploy

The `v3` function is called directly as `_find_best_play_v3(hand, table, config=config)` from `bot_sim.py`. The public `find_best_play` dispatcher is updated to accept an optional `config` kwarg and forward it to v3; v1 and v2 ignore it.

---

## What This Does NOT Do

- No LLM in the loop (no API costs)
- Does not modify game rules or bot strategy fundamentally
- Does not run on fly.io — local only
- Does not explore entirely new algorithms (hill-climbing over parameters only)
