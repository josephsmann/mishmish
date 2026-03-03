# Mish Bot Strategy

Mish Bot is the AI opponent in Mishmish, a Rummy-like card game. It uses a **greedy exhaustive search** to maximize the number of cards played from its hand in a single turn.

## Game Context

- Players hold 9 cards at the start
- A shared table holds melds (sets and runs)
- Each turn: play cards by extending existing melds or creating new ones, or draw a card
- Goal: empty your hand

**Meld types:**
- **Set**: 3+ cards of the same rank from different suits
- **Run**: 3+ consecutive cards of the same suit (wraparound supported, e.g. Q-K-A)

## Objective

The bot's single optimization target is: **play as many cards as possible this turn**.

There is no multi-turn lookahead, no opponent modeling, and no weighting by card rank or suit.

## Algorithm

The entry point is `find_best_play(hand, table)`, which returns either a new table state (if a profitable play exists) or `None` (bot draws instead).

### Phase 1: Extend Existing Melds (`_search`)

A recursive backtracking search over all table melds. For each meld the bot decides:

1. **Skip** — leave the meld unchanged
2. **Extend** — try adding some subset of compatible hand cards

Compatible cards are pre-filtered by type:
- For sets: only hand cards with the same rank
- For runs: only hand cards with the same suit

All valid combinations of compatible cards are tried via `itertools.combinations`. A candidate extension is accepted only if the resulting meld passes `is_valid_meld()`. The search recurses meld-by-meld, tracking which hand indices have been used.

**Early termination**: if a candidate play empties the hand entirely, the search stops immediately and returns that winning move.

### Phase 2: Create New Melds (`_optimal_new_melds`)

After exhausting extension possibilities for a given branch, the bot looks for new melds it can lay down from the cards still in hand.

1. Enumerate all combinations of 3+ unused hand cards
2. Keep only those that pass `is_valid_meld()`
3. Sort candidates by size (largest first) — this heuristic improves pruning
4. Use a second backtracking pass (`_bt`) to find the maximum-weight non-overlapping set of new melds

### Best-Move Selection

After the search completes, the play that used the most hand cards wins. Ties are broken arbitrarily (first found).

If no valid play is found at all, `find_best_play` returns `None` and the bot draws.

## Properties

| Property | Value |
|---|---|
| Optimization target | Cards played this turn |
| Search method | Exhaustive backtracking with pruning |
| Lookahead | None (single-turn greedy) |
| Opponent awareness | None |
| Winning-move shortcut | Yes — stops as soon as hand can be emptied |
| Complexity | O(2^hand_size) worst case; practical due to pruning and 104-card deck limit |

## Strengths and Weaknesses

**Strengths**
- Optimal for the single-turn objective
- Reliably empties the hand quickly when a path exists
- Efficient in practice due to early termination and compatibility filtering

**Weaknesses**
- Purely myopic — no consideration of future turns
- Cannot hold back cards strategically
- Ignores opponent's hand size or likely next moves
