from itertools import combinations
from typing import List, Optional, Tuple, FrozenSet

from deck import Card, RANKS, is_valid_set, is_valid_run


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns new full table state (existing melds + new melds played from hand)
    if the bot can make a valid play, or None if the bot should draw.
    """
    candidates = _find_sets(hand) + _find_runs(hand)
    chosen = _greedy_cover(candidates)
    if not chosen:
        return None
    new_melds = [cards for _, cards in chosen]
    return list(table) + new_melds


# ---- Candidate finders ----

def _find_sets(hand: List[Card]) -> List[Tuple[FrozenSet[int], List[Card]]]:
    by_rank: dict = {}
    for i, card in enumerate(hand):
        by_rank.setdefault(card['rank'], []).append(i)

    candidates = []
    for indices in by_rank.values():
        if len(indices) < 3:
            continue
        for size in range(3, len(indices) + 1):
            for combo in combinations(indices, size):
                cards = [hand[i] for i in combo]
                if is_valid_set(cards):
                    candidates.append((frozenset(combo), cards))
    return candidates


def _find_runs(hand: List[Card]) -> List[Tuple[FrozenSet[int], List[Card]]]:
    by_suit: dict = {}
    for i, card in enumerate(hand):
        by_suit.setdefault(card['suit'], []).append(i)

    candidates = []
    for indices in by_suit.values():
        # One card per rank (first occurrence) to avoid duplicate-rank issues
        rank_to_idx: dict = {}
        for i in indices:
            rank = hand[i]['rank']
            if rank not in rank_to_idx:
                rank_to_idx[rank] = i

        rank_positions = sorted(
            (RANKS.index(r), idx) for r, idx in rank_to_idx.items()
        )
        if len(rank_positions) < 3:
            continue

        sorted_pos = [rp[0] for rp in rank_positions]
        sorted_idx = [rp[1] for rp in rank_positions]
        n = len(sorted_pos)

        # Normal consecutive runs
        for start in range(n):
            for end in range(start + 2, n):
                sub_pos = sorted_pos[start:end + 1]
                sub_idx = sorted_idx[start:end + 1]
                if sub_pos[-1] - sub_pos[0] == len(sub_pos) - 1:
                    cards = [hand[i] for i in sub_idx]
                    if is_valid_run(cards):
                        candidates.append((frozenset(sub_idx), cards))

        # Wrap-around runs (e.g. Q K A 2 3)
        for size in range(3, n + 1):
            for combo in combinations(range(n), size):
                pos_combo = [sorted_pos[j] for j in combo]
                if pos_combo[-1] - pos_combo[0] == size - 1:
                    continue  # already covered above
                idx_combo = [sorted_idx[j] for j in combo]
                cards = [hand[i] for i in idx_combo]
                if is_valid_run(cards):
                    candidates.append((frozenset(idx_combo), cards))

    return candidates


# ---- Greedy cover ----

def _greedy_cover(
    candidates: List[Tuple[FrozenSet[int], List[Card]]]
) -> List[Tuple[FrozenSet[int], List[Card]]]:
    """Pick the largest non-overlapping set of melds."""
    sorted_candidates = sorted(candidates, key=lambda x: len(x[0]), reverse=True)
    used: FrozenSet[int] = frozenset()
    chosen = []
    for idx_set, cards in sorted_candidates:
        if idx_set.isdisjoint(used):
            used = used | idx_set
            chosen.append((idx_set, cards))
    return chosen
