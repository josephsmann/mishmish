"""
Tests for game lifecycle: abort, lobby visibility, reconnection to playing games.

Run with: uv run pytest tests/ -v
"""
import json
import anyio
import pytest
from fastapi.testclient import TestClient

import main
from main import app, connections, player_games, lobby


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_reconnection.py)
# ---------------------------------------------------------------------------

def reset_state():
    connections.clear()
    player_games.clear()
    lobby.games.clear()


def recv(ws) -> dict:
    return json.loads(ws.receive_text())


def send(ws, msg: dict):
    ws.send_text(json.dumps(msg))


def drain_all(ws, window_s: float = 0.08) -> list[dict]:
    results = []

    async def _try_recv():
        with anyio.move_on_after(window_s):
            return await ws._send_rx.receive()
        return None

    while True:
        msg = ws.portal.call(_try_recv)
        if msg is None:
            break
        if msg.get("type") == "websocket.send":
            text = msg.get("text") or msg.get("bytes", b"").decode()
            results.append(json.loads(text))

    return results


def find(msgs: list[dict], msg_type: str) -> dict | None:
    return next((m for m in msgs if m.get("type") == msg_type), None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    reset_state()
    yield
    reset_state()


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers to set up game state
# ---------------------------------------------------------------------------

def _two_player_waiting_game(client) -> tuple[str, str, str]:
    """Return (pid1, pid2, game_id) with both players in a waiting game."""
    with client.websocket_connect("/ws") as ws1:
        pid1 = recv(ws1)["player_id"]
        recv(ws1)  # lobby_state
        send(ws1, {"type": "create_game", "name": "Alice"})
        game_id = recv(ws1)["game_id"]
        drain_all(ws1)

        with client.websocket_connect("/ws") as ws2:
            pid2 = recv(ws2)["player_id"]
            recv(ws2)
            send(ws2, {"type": "join_game", "game_id": game_id, "name": "Bob"})
            drain_all(ws2)
            drain_all(ws1)
            # both disconnect
        # ws1 disconnects

    return pid1, pid2, game_id


def _two_player_playing_game(client) -> tuple[str, str, str]:
    """Return (pid1, pid2, game_id) with game in 'playing' status, both disconnected."""
    with client.websocket_connect("/ws") as ws1:
        pid1 = recv(ws1)["player_id"]
        recv(ws1)
        send(ws1, {"type": "create_game", "name": "Alice"})
        game_id = recv(ws1)["game_id"]
        drain_all(ws1)

        with client.websocket_connect("/ws") as ws2:
            pid2 = recv(ws2)["player_id"]
            recv(ws2)
            send(ws2, {"type": "join_game", "game_id": game_id, "name": "Bob"})
            drain_all(ws2)
            drain_all(ws1)

            send(ws1, {"type": "start_game"})
            drain_all(ws1)
            drain_all(ws2)

    assert lobby.get_game(game_id).status == "playing"
    return pid1, pid2, game_id


# ---------------------------------------------------------------------------
# Lobby visibility
# ---------------------------------------------------------------------------

class TestLobbyVisibility:
    def test_waiting_game_appears_in_lobby(self, client):
        """A newly created waiting game should appear in lobby_state."""
        with client.websocket_connect("/ws") as ws:
            recv(ws)  # connected
            recv(ws)  # lobby_state
            send(ws, {"type": "create_game", "name": "Alice"})
            recv(ws)  # joined_game
            msgs = drain_all(ws)

        # game should be in lobby_state sent to other observers
        games = lobby.list_games()
        assert len(games) == 1
        assert games[0]["status"] == "waiting"

    def test_playing_game_not_in_lobby(self, client):
        """Once a game starts, it must not appear in lobby listings."""
        pid1, pid2, game_id = _two_player_playing_game(client)
        games = lobby.list_games()
        assert all(g["game_id"] != game_id for g in games), \
            "Playing game must not appear in lobby"

    def test_lobby_state_sent_to_new_connection_excludes_playing(self, client):
        """A fresh connection's lobby_state must not include in-progress games."""
        pid1, pid2, game_id = _two_player_playing_game(client)

        with client.websocket_connect("/ws") as ws:
            recv(ws)  # connected
            lobby_msg = recv(ws)  # lobby_state
            assert lobby_msg["type"] == "lobby_state"
            game_ids = [g["game_id"] for g in lobby_msg["games"]]
            assert game_id not in game_ids


# ---------------------------------------------------------------------------
# Abort by non-creator
# ---------------------------------------------------------------------------

class TestAbortGame:
    def test_creator_can_abort_waiting_game(self, client):
        """Creator can abort a waiting game and both players receive game_aborted."""
        pid1, pid2, game_id = _two_player_waiting_game(client)

        with client.websocket_connect("/ws") as ws1:
            recv(ws1); recv(ws1)
            send(ws1, {"type": "hello", "saved_player_id": pid1})
            recv(ws1)  # hello_result
            recv(ws1)  # game_state (waiting)

            send(ws1, {"type": "abort_game"})
            msg = recv(ws1)
            assert msg["type"] == "game_aborted"
            assert msg.get("reason") == "self"

        assert lobby.get_game(game_id) is None
        assert player_games.get(pid1) is None
        assert player_games.get(pid2) is None

    def test_non_creator_can_abort_waiting_game(self, client):
        """Non-creator can also abort a waiting game."""
        pid1, pid2, game_id = _two_player_waiting_game(client)

        with client.websocket_connect("/ws") as ws2:
            recv(ws2); recv(ws2)
            send(ws2, {"type": "hello", "saved_player_id": pid2})
            recv(ws2)  # hello_result
            recv(ws2)  # game_state

            send(ws2, {"type": "abort_game"})
            msg = recv(ws2)
            assert msg["type"] == "game_aborted"
            assert msg.get("reason") == "self"

        assert lobby.get_game(game_id) is None
        assert player_games.get(pid1) is None
        assert player_games.get(pid2) is None

    def test_creator_can_abort_playing_game(self, client):
        """Creator can abort an in-progress game."""
        pid1, pid2, game_id = _two_player_playing_game(client)

        with client.websocket_connect("/ws") as ws1:
            recv(ws1); recv(ws1)
            send(ws1, {"type": "hello", "saved_player_id": pid1})
            recv(ws1)  # hello_result
            recv(ws1)  # game_state

            send(ws1, {"type": "abort_game"})
            msg = recv(ws1)
            assert msg["type"] == "game_aborted"
            assert msg.get("reason") == "self"

        assert lobby.get_game(game_id) is None

    def test_non_creator_can_abort_playing_game(self, client):
        """Non-creator can abort an in-progress game."""
        pid1, pid2, game_id = _two_player_playing_game(client)

        with client.websocket_connect("/ws") as ws2:
            recv(ws2); recv(ws2)
            send(ws2, {"type": "hello", "saved_player_id": pid2})
            recv(ws2)  # hello_result
            recv(ws2)  # game_state

            send(ws2, {"type": "abort_game"})
            msg = recv(ws2)
            assert msg["type"] == "game_aborted"
            assert msg.get("reason") == "self"

        assert lobby.get_game(game_id) is None
        assert player_games.get(pid1) is None
        assert player_games.get(pid2) is None

    def test_aborted_game_removed_from_lobby(self, client):
        """After abort, no trace of the game appears in subsequent lobby_state."""
        pid1, pid2, game_id = _two_player_waiting_game(client)

        with client.websocket_connect("/ws") as ws1:
            recv(ws1); recv(ws1)
            send(ws1, {"type": "hello", "saved_player_id": pid1})
            recv(ws1)  # hello_result
            recv(ws1)  # game_state

            send(ws1, {"type": "abort_game"})
            recv(ws1)  # game_aborted
            lobby_msg = recv(ws1)  # lobby_state
            assert lobby_msg["type"] == "lobby_state"
            assert all(g["game_id"] != game_id for g in lobby_msg["games"])

    def test_abort_notifies_connected_other_player(self, client):
        """When creator aborts, connected non-creator receives game_aborted with reason=other."""
        with client.websocket_connect("/ws") as ws1:
            pid1 = recv(ws1)["player_id"]
            recv(ws1)
            send(ws1, {"type": "create_game", "name": "Alice"})
            game_id = recv(ws1)["game_id"]
            drain_all(ws1)

            with client.websocket_connect("/ws") as ws2:
                pid2 = recv(ws2)["player_id"]
                recv(ws2)
                send(ws2, {"type": "join_game", "game_id": game_id, "name": "Bob"})
                drain_all(ws2)
                drain_all(ws1)

                # Creator aborts while both are connected
                send(ws1, {"type": "abort_game"})
                recv(ws1)  # game_aborted (reason=self)

                msg = recv(ws2)
                assert msg["type"] == "game_aborted"
                assert msg.get("reason") == "other"

    def test_abort_fails_when_not_in_game(self, client):
        """abort_game with no active game returns an error."""
        with client.websocket_connect("/ws") as ws:
            recv(ws); recv(ws)
            send(ws, {"type": "abort_game"})
            msg = recv(ws)
            assert msg["type"] == "error"


# ---------------------------------------------------------------------------
# Reconnect to abandoned playing game + abort
# ---------------------------------------------------------------------------

class TestAbandonedGameAbort:
    def test_reconnected_player_can_abort_abandoned_game(self, client):
        """Player reconnects to an abandoned playing game and aborts it cleanly."""
        pid1, pid2, game_id = _two_player_playing_game(client)

        with client.websocket_connect("/ws") as ws:
            recv(ws); recv(ws)
            send(ws, {"type": "hello", "saved_player_id": pid1})
            recv(ws)  # hello_result
            recv(ws)  # game_state (playing)

            send(ws, {"type": "abort_game"})
            msg = recv(ws)
            assert msg["type"] == "game_aborted"

        assert lobby.get_game(game_id) is None
        assert player_games.get(pid1) is None
        assert player_games.get(pid2) is None
