"""
bot_sim.py — In-process Mishmish game simulator for bot tournament use.

simulate_game(config_a, config_b) -> "a" | "b" | "draw"

Runs a complete game between two bot configs using Game directly.
No HTTP, WebSocket, or ProcessPoolExecutor involved.
"""
import uuid
from typing import Literal

from bot import BotConfig, _find_best_play_v3
from game import Game

TURN_CAP = 500


def simulate_game(
    config_a: BotConfig,
    config_b: BotConfig,
) -> Literal["a", "b", "draw"]:
    """
    Play one complete game between config_a (player index 0 = non-dealer,
    goes first) and config_b (player index 1 = dealer).

    Returns "a" if config_a's bot wins, "b" if config_b's bot wins,
    "draw" if the deck is exhausted or the turn cap is reached.
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

        new_table = _find_best_play_v3(hand, game.table, config=config)

        if new_table is not None:
            ok, msg = game.play_turn(pid, new_table)
            if not ok:
                # v3 produced an invalid table — fall back to drawing
                fallback_count += 1
                game.draw_card(pid)
        else:
            game.draw_card(pid)
            # draw_card may end the game on deck exhaustion

        if game.status == "ended":
            break

    if fallback_count > 0:
        print(f"[warn] {fallback_count} invalid play_turn calls fell back to draw")

    if game.status != "ended":
        return "draw"

    if game.winner_id is None:
        return "draw"

    return id_to_key.get(game.winner_id, "draw")
