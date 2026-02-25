from itertools import combinations
from typing import List, Optional, FrozenSet

from deck import Card, is_valid_meld


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns a new full table state that maximises cards played from hand,
    or None if the bot should draw instead.

    Strategy: backtracking search over all combinations of
    (a) extending existing table melds with hand cards, and
    (b) creating new melds from remaining hand cards.
    Picks the combination that removes the most cards from hand.
    A winning move (empties hand) is returned immediately.
    """
    best = [frozenset(), list(table)]  # [used_hand_indices, resulting_table]
    _search(hand, table, 0, frozenset(), list(table), best)
    if not best[0]:
        return None
    return best[1]


# ── Extension search ──────────────────────────────────────────────────────────

def _search(hand, orig_table, meld_idx, used, cur_table, best):
    """
    Recurse through each table meld deciding whether/how to extend it,
    then find the best new melds from remaining hand cards.
    """
    if len(best[0]) == len(hand):   # already found a winning play
        return

    if meld_idx == len(orig_table):
        # Done with extensions — maximise new melds from leftover cards
        unused = [i for i in range(len(hand)) if i not in used]
        new_used, new_melds = _optimal_new_melds(hand, unused)
        total = used | new_used
        if len(total) > len(best[0]):
            best[0] = total
            best[1] = cur_table + new_melds
        return

    # Branch 1: skip this meld
    _search(hand, orig_table, meld_idx + 1, used, cur_table, best)
    if len(best[0]) == len(hand):
        return

    # Branch 2: extend this meld with some subset of compatible hand cards
    meld = cur_table[meld_idx]
    compatible = _compatible_unused(hand, meld, used)
    for size in range(1, len(compatible) + 1):
        for combo in combinations(compatible, size):
            extended = meld + [hand[i] for i in combo]
            if is_valid_meld(extended):
                new_table = cur_table[:meld_idx] + [extended] + cur_table[meld_idx + 1:]
                _search(hand, orig_table, meld_idx + 1,
                        used | frozenset(combo), new_table, best)
                if len(best[0]) == len(hand):
                    return


def _compatible_unused(hand, meld, used):
    """
    Indices of unused hand cards that could plausibly extend this meld.
    For sets: same rank.  For runs: same suit.
    Actual validity is confirmed by is_valid_meld after appending.
    """
    unused = [i for i in range(len(hand)) if i not in used]
    if len(set(c['rank'] for c in meld)) == 1:   # set meld
        rank = meld[0]['rank']
        return [i for i in unused if hand[i]['rank'] == rank]
    else:                                          # run meld
        suit = meld[0]['suit']
        return [i for i in unused if hand[i]['suit'] == suit]


# ── New-meld search ───────────────────────────────────────────────────────────

def _optimal_new_melds(hand, unused_indices):
    """
    Find the maximum-weight set of non-overlapping new melds that can be
    formed from the given unused hand indices.
    Returns (frozenset_of_used_indices, list_of_meld_card_lists).
    """
    if len(unused_indices) < 3:
        return frozenset(), []

    candidates = []
    for size in range(3, len(unused_indices) + 1):
        for combo in combinations(unused_indices, size):
            cards = [hand[i] for i in combo]
            if is_valid_meld(cards):
                candidates.append((frozenset(combo), cards))

    if not candidates:
        return frozenset(), []

    # Largest melds first for better pruning
    candidates.sort(key=lambda x: len(x[0]), reverse=True)
    best: list = [frozenset(), []]

    def _bt(idx, used, cur_melds):
        if len(used) > len(best[0]):
            best[0] = used
            best[1] = cur_melds[:]
        if idx >= len(candidates) or len(best[0]) == len(unused_indices):
            return
        for i in range(idx, len(candidates)):
            indices, cards = candidates[i]
            if indices.isdisjoint(used):
                _bt(i + 1, used | indices, cur_melds + [cards])

    _bt(0, frozenset(), [])
    return best[0], best[1]
