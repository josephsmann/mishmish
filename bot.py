from collections import defaultdict
from itertools import combinations
from typing import List, Optional, FrozenSet

from deck import Card, is_valid_run, is_valid_set


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns a new full table state that maximises cards played from hand,
    or None if the bot should draw instead.

    Pool indices 0..n_table-1 are table cards (must all be covered);
    n_table..end are hand cards (optional, maximise coverage).

    A single exact-cover pass branches only on uncovered table cards
    (tightly constrained), then greedily packs any remaining hand cards
    into new melds at the end.  This allows splitting and reorganising
    existing table melds without the 2^hand_size subset explosion.
    """
    table_cards = [card for meld in table for card in meld]
    n_table = len(table_cards)
    pool = table_cards + hand
    n_pool = len(pool)

    if not pool:
        return None

    candidates = _build_candidates(pool)

    # covers[i] = list of candidate indices whose meld contains pool[i]
    covers: List[List[int]] = [[] for _ in range(n_pool)]
    for ci, (indices, _) in enumerate(candidates):
        for idx in indices:
            covers[idx].append(ci)

    best = [0, list(table)]  # [hand_cards_played, resulting_table]

    def bt(covered: FrozenSet[int], melds: list) -> bool:
        # Find the first uncovered TABLE card (must be covered to keep table valid)
        first_table = next((i for i in range(n_table) if i not in covered), None)

        if first_table is None:
            # All table cards are in valid melds.  Now pack remaining hand cards.
            unused_hand = [i for i in range(n_table, n_pool) if i not in covered]
            hand_in_melds = sum(1 for i in range(n_table, n_pool) if i in covered)
            extra_used, extra_melds = _pack_hand(pool, unused_hand, candidates)
            total = hand_in_melds + len(extra_used)
            if total > best[0]:
                best[0] = total
                best[1] = melds + extra_melds
            return total == len(hand)  # winning move — stop early

        # Branch: try every candidate meld that covers first_table
        for ci in covers[first_table]:
            indices, meld_cards = candidates[ci]
            if indices.isdisjoint(covered):
                if bt(covered | indices, melds + [meld_cards]):
                    return True
        return False

    bt(frozenset(), [])

    return None if best[0] == 0 else best[1]


# ── Candidate generation ──────────────────────────────────────────────────────

def _build_candidates(cards: List[Card]):
    """
    Enumerate all valid melds formable from `cards` as (frozenset_of_indices,
    card_list) pairs.  Candidates are generated within same-rank groups (sets)
    and same-suit groups (runs) only — much cheaper than trying all C(n, k).
    """
    candidates = []

    by_rank: dict = defaultdict(list)
    for i, c in enumerate(cards):
        by_rank[c['rank']].append(i)
    for indices in by_rank.values():
        for size in range(3, len(indices) + 1):
            for combo in combinations(indices, size):
                meld_cards = [cards[i] for i in combo]
                if is_valid_set(meld_cards):
                    candidates.append((frozenset(combo), meld_cards))

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


# ── Hand-card packing ─────────────────────────────────────────────────────────

def _pack_hand(pool: List[Card], unused_hand: List[int], all_candidates):
    """
    Find the maximum-weight non-overlapping set of melds formable purely
    from `unused_hand` indices (no table cards), using the pre-built
    candidate list to avoid regenerating melds.
    """
    if len(unused_hand) < 3:
        return frozenset(), []

    hand_set = frozenset(unused_hand)
    relevant = [(idx, cards) for idx, cards in all_candidates
                if idx.issubset(hand_set)]
    if not relevant:
        return frozenset(), []

    relevant.sort(key=lambda x: len(x[0]), reverse=True)
    best: list = [frozenset(), []]

    def _bt(i: int, used: FrozenSet[int], cur_melds: list) -> None:
        if len(used) > len(best[0]):
            best[0] = used
            best[1] = cur_melds[:]
        if i >= len(relevant) or len(best[0]) == len(unused_hand):
            return
        for j in range(i, len(relevant)):
            indices, cards = relevant[j]
            if indices.isdisjoint(used):
                _bt(j + 1, used | indices, cur_melds + [cards])

    _bt(0, frozenset(), [])
    return best[0], best[1]
