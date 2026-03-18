"""
bot_sim.py — In-process Mishmish game simulator for bot tournament use.

simulate_game(config_a, config_b) -> "a" | "b" | "tie"

Runs a complete game between two bot configs using Game directly.
No HTTP, WebSocket, or ProcessPoolExecutor involved.

Terminology:
  "pick"  — a player takes a card from the deck (no meld to play)
  "tie"   — game ends with no winner (deck exhausted or turn cap hit)

Note: the underlying Game API uses draw_card() for picking — that name
is part of the WebSocket protocol and unchanged here.
"""
import uuid
from typing import Literal

from bot import BotConfig, _build_candidates, _find_best_play_v2
from game import Game

TURN_CAP = 500


def _sim_play(hand, table, lam: float, _v2_pool_limit: int = 40):
    """
    Fast greedy play for simulation. Always plays the best-scoring meld when
    any valid play exists; returns None only if no meld is possible (bot picks).

    Uses v3-style greedy scoring (cards_from_hand - lam * opportunities) but
    with a -inf threshold so it never strategically passes — decisive outcomes
    over conservative ones for simulation purposes.

    For small pools (hand + table ≤ _v2_pool_limit), delegates to v2 which
    handles full table rearrangement and produces more realistic play.
    """
    table_cards = [c for meld in table for c in meld]
    if len(table_cards) + len(hand) <= _v2_pool_limit:
        return _find_best_play_v2(hand, table, lam=lam)

    # (A) All-hand candidates
    hand_cands = _build_candidates(hand)
    hand_idx_sets = [frozenset(idx) for idx, _ in hand_cands]

    play_options = []
    for (indices, meld_cards), idx_set in zip(hand_cands, hand_idx_sets):
        def make_new(mc=meld_cards):
            return list(table) + [mc]
        play_options.append((idx_set, len(indices), make_new))

    # (B) Meld-extension candidates
    for mi, meld in enumerate(table):
        small_pool = list(meld) + list(hand)
        n_meld = len(meld)
        for indices, ext_meld in _build_candidates(small_pool):
            idx_set = frozenset(indices)
            meld_bits = frozenset(range(n_meld))
            if not meld_bits <= idx_set:
                continue
            hand_bits = frozenset(i - n_meld for i in idx_set if i >= n_meld)
            if not hand_bits:
                continue
            def make_ext(midx=mi, em=ext_meld):
                nt = list(table)
                nt[midx] = em
                return nt
            play_options.append((hand_bits, len(hand_bits), make_ext))

    if not play_options:
        return None

    best_score = float("-inf")
    best_play = None
    for hand_bits, n_from_hand, new_table_fn in play_options:
        opps = sum(1 for s in hand_idx_sets if s <= hand_bits)
        score = n_from_hand - lam * opps
        if score > best_score:
            best_score = score
            best_play = (hand_bits, new_table_fn)

    hand_bits, new_table_fn = best_play
    new_table = new_table_fn()

    # Pack remaining hand cards into additional melds
    remaining = [hand[j] for j in range(len(hand)) if j not in hand_bits]
    used: set = set()
    for ex_idx, ex_cards in _build_candidates(remaining):
        ex_set = frozenset(ex_idx)
        if ex_set.isdisjoint(used):
            new_table.append(ex_cards)
            used |= ex_set

    return new_table


def simulate_game(
    config_a: BotConfig,
    config_b: BotConfig,
) -> Literal["a", "b", "tie"]:
    """
    Play one complete game between config_a (player index 0 = non-dealer,
    goes first) and config_b (player index 1 = dealer).

    Returns "a" if config_a's bot wins, "b" if config_b's bot wins,
    "tie" if the deck is exhausted or the turn cap is reached.
    """
    bot_a_id = "bot_a_" + uuid.uuid4().hex[:6]
    bot_b_id = "bot_b_" + uuid.uuid4().hex[:6]

    game = Game(game_id=uuid.uuid4().hex[:8], creator_id=bot_a_id)
    game.add_player(bot_a_id, "Bot A", is_bot=True)
    game.add_player(bot_b_id, "Bot B", is_bot=True)
    game.start(requestor_id=bot_a_id)

    config_map = {bot_a_id: config_a, bot_b_id: config_b}
    id_to_key = {bot_a_id: "a", bot_b_id: "b"}

    fallback_count = 0
    for _ in range(TURN_CAP):
        if game.status == "ended":
            break

        current = game._get_current_player()
        if current is None:
            break

        pid = current["id"]
        hand = current["hand"]
        config = config_map[pid]

        new_table = _sim_play(hand, game.table, lam=config.lam)

        if new_table is not None:
            ok, msg = game.play_turn(pid, new_table)
            if not ok:
                # _sim_play produced an invalid table — bot picks instead
                fallback_count += 1
                game.draw_card(pid)  # game API: draw_card = pick from deck
        else:
            game.draw_card(pid)  # game API: draw_card = pick from deck

        if game.status == "ended":
            break

    if fallback_count > 0:
        print(f"[warn] {fallback_count} invalid play_turn calls fell back to pick")

    if game.status != "ended":
        return "tie"  # turn cap hit

    if game.winner_id is None:
        return "tie"  # deck exhausted

    return id_to_key.get(game.winner_id, "tie")
