from collections import defaultdict
from itertools import combinations, product as iproduct
from typing import List, Optional

from dataclasses import dataclass

from deck import Card, RANKS, is_valid_set


@dataclass
class BotConfig:
    lam: float = 0.5
    hand_cutoff: int = 10

_N_RANKS = len(RANKS)


def _find_best_play_v1(
    hand: List[Card],
    table: List[List[Card]],
) -> Optional[List[List[Card]]]:
    """
    Returns a new full table state that maximises cards played from hand,
    or None if the bot should draw instead.

    Pool indices 0..n_table-1 are table cards (must all be covered);
    n_table..end are hand cards (optional, maximise coverage).

    Uses exact-cover backtracking with:
    - MRV heuristic (most-constrained table card first)
    - Bitmask representation for O(1) cover/uncover operations
    - Precomputed candidate signatures to skip isomorphic branches
    """
    table_cards = [card for meld in table for card in meld]
    n_table = len(table_cards)
    pool = table_cards + hand
    n_pool = len(pool)

    if not pool:
        return None

    candidates = _build_candidates(pool)

    # Pre-compute per-candidate bitmasks, card lists, and signatures.
    # Signatures deduplicate branches that differ only in which physical copy
    # of an identical card is used — they lead to isomorphic sub-problems.
    cand_masks: List[int] = []
    cand_cards: List[list] = []
    cand_sigs: List[tuple] = []
    for indices, meld_cards in candidates:
        mask = 0
        for i in indices:
            mask |= 1 << i
        cand_masks.append(mask)
        cand_cards.append(meld_cards)
        cand_sigs.append(tuple(sorted(
            (pool[i]['rank'], pool[i]['suit'], i >= n_table)
            for i in indices
        )))

    # covers[i] = list of candidate indices whose meld contains pool[i]
    covers: List[List[int]] = [[] for _ in range(n_pool)]
    for ci, (indices, _) in enumerate(candidates):
        for idx in indices:
            covers[idx].append(ci)

    best = [0, list(table)]  # [hand_cards_played, resulting_table]

    def bt(covered: int, melds: list) -> bool:
        # MRV: among uncovered table cards, pick the one with fewest valid
        # candidates. This is the "most constrained variable" heuristic —
        # fail fast on dead branches.
        best_count = None
        target = -1
        for i in range(n_table):
            if (covered >> i) & 1:
                continue
            cnt = sum(1 for ci in covers[i] if (cand_masks[ci] & covered) == 0)
            if cnt == 0:
                return False  # card can never be covered — prune immediately
            if best_count is None or cnt < best_count:
                best_count = cnt
                target = i

        if target == -1:
            # All table cards covered — pack remaining hand cards into new melds.
            hand_in_melds = bin(covered >> n_table).count('1')
            unused_hand = [
                n_table + j for j in range(len(hand))
                if not ((covered >> (n_table + j)) & 1)
            ]
            extra_used, extra_melds = _pack_hand(pool, unused_hand, candidates)
            total = hand_in_melds + len(extra_used)
            if total > best[0]:
                best[0] = total
                best[1] = melds + extra_melds
            return total == len(hand)  # winning move — stop early

        tried_sigs: set = set()
        for ci in covers[target]:
            if (cand_masks[ci] & covered) == 0:
                sig = cand_sigs[ci]
                if sig in tried_sigs:
                    continue
                tried_sigs.add(sig)
                if bt(covered | cand_masks[ci], melds + [cand_cards[ci]]):
                    return True
        return False

    bt(0, [])

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

    Branch-and-bound: precomputes an upper bound (sum of remaining meld sizes,
    ignoring overlaps) and prunes any branch that cannot beat the current best.
    """
    if len(unused_hand) < 3:
        return frozenset(), []

    hand_set = frozenset(unused_hand)
    relevant = [(idx, cards) for idx, cards in all_candidates
                if idx.issubset(hand_set)]
    if not relevant:
        return frozenset(), []

    relevant.sort(key=lambda x: len(x[0]), reverse=True)

    # Precompute upper bound: max cards reachable from position i onward.
    # This ignores card overlaps so it safely overestimates — valid for pruning.
    max_from = [0] * (len(relevant) + 1)
    for i in range(len(relevant) - 1, -1, -1):
        max_from[i] = max_from[i + 1] + len(relevant[i][0])

    best: list = [frozenset(), []]

    def _bt(i: int, used: frozenset, cur_melds: list) -> None:
        cur = len(used)
        if cur > len(best[0]):
            best[0] = used
            best[1] = cur_melds[:]
        if cur == len(unused_hand) or i >= len(relevant):
            return
        # Prune: even taking every remaining card can't beat current best
        if cur + max_from[i] <= len(best[0]):
            return
        for j in range(i, len(relevant)):
            # Since relevant is sorted descending, max_from[j] only shrinks —
            # once we can't beat best, no later candidate can either.
            if cur + max_from[j] <= len(best[0]):
                break
            indices, cards = relevant[j]
            if indices.isdisjoint(used):
                _bt(j + 1, used | indices, cur_melds + [cards])

    _bt(0, frozenset(), [])
    return best[0], best[1]


# ── V2: opportunity-aware scoring ─────────────────────────────────────────────

_LAMBDA = 0.5  # blocking weight: cards_played − λ × new_table_opportunities


def _find_best_play_v2(
    hand: List[Card],
    table: List[List[Card]],
    lam: float = _LAMBDA,
) -> Optional[List[List[Card]]]:
    """
    Score-based bot: picks the play that maximises
        cards_played_from_hand − λ × new_meld_opportunities(new_table)

    "new_meld_opportunities" = number of distinct valid melds formable
    from the new table's cards alone (computed via _build_candidates).
    This penalises plays that enrich the shared table for the opponent.

    Falls back to drawing if every play scores ≤ 0.
    """
    if not hand:
        return None

    table_cards = [card for meld in table for card in meld]
    n_table = len(table_cards)
    pool = table_cards + hand
    n_pool = len(pool)

    candidates = _build_candidates(pool)

    cand_masks: List[int] = []
    cand_cards: List[list] = []
    cand_sigs: List[tuple] = []
    for indices, meld_cards in candidates:
        mask = 0
        for i in indices:
            mask |= 1 << i
        cand_masks.append(mask)
        cand_cards.append(meld_cards)
        cand_sigs.append(tuple(sorted(
            (pool[i]['rank'], pool[i]['suit'], i >= n_table)
            for i in indices
        )))

    covers: List[List[int]] = [[] for _ in range(n_pool)]
    for ci, (indices, _) in enumerate(candidates):
        for idx in indices:
            covers[idx].append(ci)

    # best = [score, table_state]; -inf ensures any valid play wins
    best = [float('-inf'), None]

    # hand_mask: bitmask of all hand card positions
    hand_mask = ((1 << len(hand)) - 1) << n_table

    def bt(covered: int, melds: list) -> bool:
        best_count = None
        target = -1
        for i in range(n_table):
            if (covered >> i) & 1:
                continue
            cnt = sum(1 for ci in covers[i] if (cand_masks[ci] & covered) == 0)
            if cnt == 0:
                return False
            if best_count is None or cnt < best_count:
                best_count = cnt
                target = i

        if target == -1:
            # All table cards covered — pack remaining hand cards.
            hand_in_melds = bin(covered >> n_table).count('1')
            unused_hand = [
                n_table + j for j in range(len(hand))
                if not ((covered >> (n_table + j)) & 1)
            ]
            extra_used, extra_melds = _pack_hand(pool, unused_hand, candidates)
            cards_played = hand_in_melds + len(extra_used)

            if cards_played == 0:
                return False

            # Compute covered mask for the final table (table cards + played hand cards).
            # A candidate is "in new table" if all its cards are covered.
            # A candidate is "new" if it includes at least one hand card.
            # Use precomputed bitmasks — O(n_candidates), no extra _build_candidates call.
            final_covered = covered | (extra_used if isinstance(extra_used, int) else
                                       sum(1 << i for i in extra_used))
            opportunities = sum(
                1 for ci in range(len(cand_masks))
                if (cand_masks[ci] & final_covered) == cand_masks[ci]   # all in new table
                and cand_masks[ci] & hand_mask                          # includes a hand card
            )
            score = cards_played - lam * opportunities

            if score > best[0]:
                best[0] = score
                best[1] = melds + extra_melds

            return cards_played == len(hand)  # early exit on winning move

        tried_sigs: set = set()
        for ci in covers[target]:
            if (cand_masks[ci] & covered) == 0:
                sig = cand_sigs[ci]
                if sig in tried_sigs:
                    continue
                tried_sigs.add(sig)
                if bt(covered | cand_masks[ci], melds + [cand_cards[ci]]):
                    return True
        return False

    bt(0, [])

    return None if best[1] is None else best[1]


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

    # Use v2 only when pool is small enough to be fast (≤20 total cards).
    table_cards_flat = [card for meld in table for card in meld]
    pool_size = len(table_cards_flat) + len(hand)
    if len(hand) <= config.hand_cutoff and pool_size <= 20:
        return _find_best_play_v2(hand, table, lam=config.lam)

    # ── Greedy path ────────────────────────────────────────────────────────
    # Fast O(hand × table_melds) approach that avoids building candidates from
    # the full (potentially huge) pool.  Enumerate two play types:
    #   (A) New all-hand melds — candidates built from `hand` only.
    #   (B) Meld extensions — append hand cards to one existing table meld,
    #       keeping ALL its original cards (so no table cards are removed).
    # Score: cards_from_hand − λ × hand_only_opportunities
    # where hand_only_opportunities = # melds formable from the played hand
    # cards alone (the genuinely new pieces placed on the shared table).

    # ── (A) All-hand candidates ────────────────────────────────────────────
    hand_only_candidates = _build_candidates(hand)
    # Precompute frozensets of hand indices for subset checks
    hand_only_index_sets: List[frozenset] = [frozenset(idx) for idx, _ in hand_only_candidates]

    # Each greedy play is:
    #   play_type: "new" | "extend"
    #   hand_bits: frozenset of hand indices used
    #   n_from_hand: number of hand cards played
    #   new_table_fn: callable() -> new table state
    play_options: List[tuple] = []

    for (indices, meld_cards), idx_set in zip(hand_only_candidates, hand_only_index_sets):
        def make_new(mc=meld_cards):
            return list(table) + [mc]
        play_options.append(("new", idx_set, len(indices), make_new))

    # ── (B) Meld-extension candidates ─────────────────────────────────────
    # Try extending each existing meld with subsets of hand cards (up to 3).
    # We do single-card extensions exhaustively; for multi-card use _build_candidates
    # on (meld + hand) with the constraint that all meld cards are included.
    for mi, meld in enumerate(table):
        small_pool = list(meld) + list(hand)
        n_meld = len(meld)
        ext_cands = _build_candidates(small_pool)
        for indices, ext_meld in ext_cands:
            idx_set = frozenset(indices)
            # Must include ALL meld cards (indices 0..n_meld-1)
            meld_bits = frozenset(range(n_meld))
            if not meld_bits <= idx_set:
                continue
            hand_bits_in_ext = frozenset(i - n_meld for i in idx_set if i >= n_meld)
            if not hand_bits_in_ext:
                continue  # no hand cards added
            n_from_hand = len(hand_bits_in_ext)
            ext_meld_copy = ext_meld  # capture
            def make_ext(midx=mi, em=ext_meld_copy):
                nt = list(table)
                nt[midx] = em
                return nt
            play_options.append(("extend", hand_bits_in_ext, n_from_hand, make_ext))

    if not play_options:
        return None

    best_score = 0.0
    best_play = None

    for play_type, hand_bits, n_from_hand, new_table_fn in play_options:
        # Opportunities: # all-hand melds that are subsets of the played hand bits
        opps = sum(1 for s in hand_only_index_sets if s <= hand_bits)
        score = n_from_hand - config.lam * opps
        if score > best_score:
            best_score = score
            best_play = (play_type, hand_bits, n_from_hand, new_table_fn)

    if best_play is None:
        return None

    play_type, hand_bits, n_from_hand, new_table_fn = best_play
    new_table = new_table_fn()

    # Greedily pack remaining hand cards into additional all-hand melds
    remaining_hand = [hand[j] for j in range(len(hand)) if j not in hand_bits]
    extra_cands = _build_candidates(remaining_hand)
    used: set = set()
    for ex_idx, ex_cards in extra_cands:
        ex_set = frozenset(ex_idx)
        if ex_set.isdisjoint(used):
            new_table.append(ex_cards)
            used |= ex_set

    return new_table


# ── Version registry ──────────────────────────────────────────────────────────

VERSIONS: dict = {
    "v1": _find_best_play_v1,
    "v2": _find_best_play_v2,
    "v3": _find_best_play_v3,
}
DEFAULT = "v2"


def find_best_play(
    hand: List[Card],
    table: List[List[Card]],
    version: str = DEFAULT,
    config: "BotConfig | None" = None,
) -> Optional[List[List[Card]]]:
    """Dispatch to the requested bot version. Falls back to DEFAULT if unknown."""
    resolved_version = version if version in VERSIONS else DEFAULT
    fn = VERSIONS[resolved_version]
    if resolved_version == "v3":
        cfg = config or BotConfig()
        return fn(hand, table, config=cfg)
    return fn(hand, table)
