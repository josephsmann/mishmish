from collections import defaultdict
from itertools import combinations, product as iproduct
from typing import List, Optional, FrozenSet

from deck import Card, RANKS, is_valid_set

_N_RANKS = len(RANKS)


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns a new full table state that maximises cards played from hand,
    or None if the bot should draw instead.

    Pool indices 0..n_table-1 are table cards (must all be covered);
    n_table..end are hand cards (optional, maximise coverage).

    Uses exact-cover backtracking with the MRV heuristic (most-constrained
    table card first) to prune the search tree aggressively.
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
        # MRV: among uncovered table cards, pick the one with fewest valid candidates.
        # This is the "most constrained variable" heuristic — fail fast on dead branches.
        best_count = None
        target = None
        for i in range(n_table):
            if i in covered:
                continue
            cnt = sum(1 for ci in covers[i] if candidates[ci][0].isdisjoint(covered))
            if cnt == 0:
                return False  # This card can never be covered — prune immediately
            if best_count is None or cnt < best_count:
                best_count = cnt
                target = i

        if target is None:
            # All table cards covered — pack remaining hand cards into new melds.
            unused_hand = [i for i in range(n_table, n_pool) if i not in covered]
            hand_in_melds = sum(1 for i in range(n_table, n_pool) if i in covered)
            extra_used, extra_melds = _pack_hand(pool, unused_hand, candidates)
            total = hand_in_melds + len(extra_used)
            if total > best[0]:
                best[0] = total
                best[1] = melds + extra_melds
            return total == len(hand)  # winning move — stop early

        for ci in covers[target]:
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
    Enumerate all valid melds formable from `cards`.

    Sets  — all valid combinations within each rank group (small: ≤ C(8,3)).
    Runs  — enumerate consecutive rank sequences directly, then use
            itertools.product over per-rank card slots.  This avoids the
            C(n_suit, k) explosion when many cards share a suit, replacing
            it with O(distinct_runs × 2^run_len) which stays small.
    """
    candidates = []

    # --- Sets ---
    by_rank: dict = defaultdict(list)
    for i, c in enumerate(cards):
        by_rank[c['rank']].append(i)
    for rank_indices in by_rank.values():
        for size in range(3, len(rank_indices) + 1):
            for combo in combinations(rank_indices, size):
                meld_cards = [cards[i] for i in combo]
                if is_valid_set(meld_cards):
                    candidates.append((frozenset(combo), meld_cards))

    # --- Runs ---
    by_suit: dict = defaultdict(list)
    for i, c in enumerate(cards):
        by_suit[c['suit']].append(i)

    for suit_indices in by_suit.values():
        # Map rank_position → pool indices for this (suit, rank)
        rank_slots: dict = defaultdict(list)
        for i in suit_indices:
            rank_slots[RANKS.index(cards[i]['rank'])].append(i)
        present = set(rank_slots.keys())

        # Enumerate all valid run starting points on the circular rank wheel.
        # For each start rank, extend as long as the next rank is also present.
        # This directly generates only valid consecutive sequences — no C(n,k).
        seen: set = set()
        for start_rank in present:
            run: List[int] = []
            r = start_rank
            while r in present or (not run):
                if r not in present:
                    break
                run.append(r)
                r = (r + 1) % _N_RANKS
                if r == start_rank:
                    break  # full circle — stop before duplicating start rank
                if len(run) > 1 and run[-1] < run[-2] and run[-1] == 0:
                    # Crossed the A→2 wraparound boundary; keep going but track it
                    pass

                if len(run) >= 3:
                    slot_choices = [rank_slots[rank] for rank in run]
                    for combo in iproduct(*slot_choices):
                        key = frozenset(combo)
                        if key not in seen:
                            seen.add(key)
                            candidates.append((key, [cards[i] for i in combo]))

    return candidates


# ── Hand-card packing ─────────────────────────────────────────────────────────

def _pack_hand(pool: List[Card], unused_hand: List[int], all_candidates):
    """
    Find the maximum-weight non-overlapping set of melds formable purely
    from `unused_hand` indices, using the pre-built candidate list.
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
