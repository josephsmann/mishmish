"""Tests for the set_bot_timeout WebSocket message."""
import os
import time
import pytest
from starlette.testclient import TestClient

os.environ.setdefault("ADMIN_KEY", "test-key")


@pytest.fixture()
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def _start_game_wait_for_human_turn(ws):
    """Create a game with a bot, start it, and drain until it's the human's turn.

    Returns game_id. Waits until your_turn=True so the bot has finished its
    first turn and the WS handler is back in the message-read loop.
    """
    ws.send_json({"type": "create_game", "name": "Human"})
    game_id = None
    for _ in range(5):
        msg = ws.receive_json()
        if msg.get("type") == "joined_game":
            game_id = msg["game_id"]
            break
    assert game_id
    ws.send_json({"type": "add_bot"})
    ws.send_json({"type": "start_game"})
    # Drain until it's the human's turn — ensures bot has completed its first
    # turn and the WS handler is back in the receive loop ready for new messages.
    for _ in range(20):
        msg = ws.receive_json()
        if msg.get("type") == "game_state" and msg["state"].get("your_turn"):
            break
    return game_id


def test_set_bot_timeout_updates_game(client):
    """Human player can set bot timeout."""
    import main
    with client.websocket_connect("/ws") as ws:
        game_id = _start_game_wait_for_human_turn(ws)

        ws.send_json({"type": "set_bot_timeout", "seconds": 30.0})
        time.sleep(0.2)

        game = main.lobby.get_game(game_id)
        assert game is not None
        assert game.bot_timeout_seconds == 30.0


def test_set_bot_timeout_clamps_low(client):
    """Seconds below 2.0 are clamped to 2.0."""
    import main
    with client.websocket_connect("/ws") as ws:
        game_id = _start_game_wait_for_human_turn(ws)

        ws.send_json({"type": "set_bot_timeout", "seconds": 0.1})
        time.sleep(0.2)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 2.0


def test_set_bot_timeout_clamps_high(client):
    """Seconds above 60.0 are clamped to 60.0."""
    import main
    with client.websocket_connect("/ws") as ws:
        game_id = _start_game_wait_for_human_turn(ws)

        ws.send_json({"type": "set_bot_timeout", "seconds": 999.0})
        time.sleep(0.2)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 60.0
