"""Tests for the set_bot_timeout WebSocket message."""
import os
import pytest
from starlette.testclient import TestClient

os.environ.setdefault("ADMIN_KEY", "test-key")


@pytest.fixture()
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def test_set_bot_timeout_updates_game(client):
    """Human player can set bot timeout; value is clamped to [2, 60]."""
    import main
    with client.websocket_connect("/ws") as ws:
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
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 30.0})
        import time; time.sleep(0.1)

        game = main.lobby.get_game(game_id)
        assert game is not None
        assert game.bot_timeout_seconds == 30.0


def test_set_bot_timeout_clamps_low(client):
    import main
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 0.1})
        import time; time.sleep(0.1)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 2.0


def test_set_bot_timeout_clamps_high(client):
    import main
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_game", "name": "Human"})
        game_id = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg.get("type") == "joined_game":
                game_id = msg["game_id"]
                break
        ws.send_json({"type": "add_bot"})
        ws.send_json({"type": "start_game"})
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "game_state" and msg["state"]["status"] == "playing":
                break

        ws.send_json({"type": "set_bot_timeout", "seconds": 999.0})
        import time; time.sleep(0.1)
        game = main.lobby.get_game(game_id)
        assert game.bot_timeout_seconds == 60.0
