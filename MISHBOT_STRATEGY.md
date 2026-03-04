# Mish Bot Strategy

Mish Bot is the AI opponent in Mishmish, a Rummy-like card game. It uses an **exact-cover search** to maximize the number of cards played from its hand in a single turn, with full freedom to split and reorganize existing table melds.

## Game Context

- Players hold 9 cards at the start
- A shared table holds melds (sets and runs)
- Each turn: play cards by extending existing melds or creating new ones, or draw a card
- Goal: empty your hand

**Meld types:**
- **Set**: 3+ cards of the same rank from different suits
- **Run**: 3+ consecutive cards of the same suit (wraparound supported, e.g. Q-K-A or A-2-3)

## Objective

The bot's single optimization target is: **play as many cards as possible this turn**.

There is no multi-turn lookahead, no opponent modeling, and no weighting by card rank or suit.

## Algorithm

The entry point is `find_best_play(hand, table)`, which runs in a `ProcessPoolExecutor` so the asyncio event loop stays responsive while the bot thinks.

### Key insight: flatten the table

All table melds are flattened into a single card pool. This allows the bot to split melds, pull cards off them, and recombine everything freely — as long as every table card ends up in a valid meld.

For example, given the table meld `2H 3H 4H 5H 6H` and a hand card `4H`, the bot can produce two melds: `2H 3H 4H` and `4H 5H 6H`.

### Pool layout

```
pool = table_cards + hand_cards
       [0 .. n_table-1]  [n_table .. end]
       must be covered    maximise coverage
```

### Step 1: Candidate generation (`_build_candidates`)

All valid melds formable from the pool are enumerated up front.

**Sets** — group cards by rank; try all combinations within each rank group. Small input (≤ 8 cards per rank in a 2-deck game).

**Runs** — instead of `combinations(n_suit_cards, k)` which blows up as C(n, k), runs are enumerated directly:
1. Group cards by suit, then by rank within each suit (`rank_slots`)
2. For each starting rank present in the suit, extend the run as long as the next consecutive rank is also present (wrapping A→2 for wraparound runs)
3. For each valid run structure, generate all index assignments via `itertools.product` over the per-rank card slots

This replaces C(n, k) with O(distinct_runs × 2^run_length), which stays small even with a full suit on the table.

### Step 2: Exact-cover search with MRV (`bt`)

A single backtracking pass covers the entire pool:

1. **MRV (Most Constrained Variable)**: among all uncovered table cards, pick the one with the fewest valid candidates remaining. If any card has zero candidates, prune the branch immediately — it can never be covered.
2. Try every candidate meld that covers the chosen card; recurse with those indices marked as used.
3. When all table cards are covered, call `_pack_hand` to greedily fill remaining hand cards into new melds.
4. Track the maximum hand cards used; stop immediately on a winning move (hand emptied).

MRV is the key pruning heuristic: failing fast on the most constrained card eliminates large subtrees early.

### Step 3: Pack remaining hand cards (`_pack_hand`)

After all table cards are covered, unused hand cards are packed into additional melds via a separate backtracking pass over pure-hand candidates, largest-first.

## Properties

| Property | Value |
| --- | --- |
| Optimization target | Cards played this turn |
| Search method | Exact-cover backtracking with MRV pruning |
| Table reorganization | Full — melds can be split and recombined |
| Candidate generation | Consecutive rank enumeration + product (not C(n,k)) |
| Lookahead | None (single-turn greedy) |
| Opponent awareness | None |
| Concurrency | Runs in ProcessPoolExecutor — event loop stays free |
| Performance | ~60ms typical for large tables |

## Strengths and Weaknesses

**Strengths**
- Finds moves that require splitting or reorganizing existing melds
- Optimal for the single-turn objective
- Fast: MRV pruning + efficient candidate generation; non-blocking via process pool

**Weaknesses**
- Purely myopic — no consideration of future turns
- Cannot hold back cards strategically
- Ignores opponent's hand size or likely next moves
