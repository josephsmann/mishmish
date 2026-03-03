from collections import defaultdict
from itertools import combinations
from typing import List, Optional, FrozenSet

from deck import Card, is_valid_meld, is_valid_run, is_valid_set


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns a new full table state that maximises cards played from hand,
    or None if the bot should draw instead.

    Strategy: flatten all table cards into a pool, then find the largest
    subset of hand cards that can be added so the entire pool re-partitions
    into valid melds.  This allows splitting and reorganising existing melds,
    not just appending to them.
    """
    table_cards = [card for meld in table for card in meld]

    # Try to play as many hand cards as possible (largest subset first).
    for size in range(len(hand), 0, -1):
        for combo in combinations(range(len(hand)), size):
            pool = table_cards + [hand[i] for i in combo]
            partition = _exact_cover(pool)
            if partition is not None:
                return partition

    return None


# ── Exact-cover search ────────────────────────────────────────────────────────

def _exact_cover(cards: List[Card]) -> Optional[List[List[Card]]]:
    """
    Partition `cards` into valid melds, or return None if impossible.

    Uses exact-cover backtracking: at each step pick the first uncovered card
    and branch over every candidate meld that covers it.  This is far more
    efficient than iterating over candidates in insertion order.
    """
    n = len(cards)
    if n < 3:
        return None

    candidates = _build_candidates(cards)
    if not candidates:
        return None

    # Index: card position → list of candidate indices that include it
    covers: List[List[int]] = [[] for _ in range(n)]
    for ci, (indices, _) in enumerate(candidates):
        for idx in indices:
            covers[idx].append(ci)

    result: List = [None]

    def bt(used: FrozenSet[int], melds: list) -> bool:
        if len(used) == n:
            result[0] = melds[:]
            return True
        # Find the first uncovered position
        first = next(i for i in range(n) if i not in used)
        # Branch on each candidate meld that covers `first`
        for ci in covers[first]:
            indices, meld_cards = candidates[ci]
            if indices.isdisjoint(used):
                if bt(used | indices, melds + [meld_cards]):
                    return True
        return False

    bt(frozenset(), [])
    return result[0]


def _build_candidates(cards: List[Card]):
    """
    Enumerate all valid melds that can be formed from `cards`, returning a
    list of (frozenset_of_indices, card_list) pairs.

    Candidates are generated within same-rank groups (sets) and same-suit
    groups (runs) only, which is far cheaper than trying all C(n, k).
    """
    n = len(cards)
    candidates = []

    # Sets: all valid combinations within each rank group
    by_rank: dict = defaultdict(list)
    for i, c in enumerate(cards):
        by_rank[c['rank']].append(i)
    for indices in by_rank.values():
        for size in range(3, len(indices) + 1):
            for combo in combinations(indices, size):
                meld_cards = [cards[i] for i in combo]
                if is_valid_set(meld_cards):
                    candidates.append((frozenset(combo), meld_cards))

    # Runs: all valid combinations within each suit group
    by_suit: dict = defaultdict(list)
    for i, c in enumerate(cards):
        by_suit[c['suit']].append(i)
    for indices in by_suit.values():
        for size in range(3, len(indices) + 1):
            for combo in combinations(indices, size):
                meld_cards = [cards[i] for i in combo]
                if is_valid_run(meld_cards):
                    candidates.append((frozenset(combo), meld_cards))

    return candidates
