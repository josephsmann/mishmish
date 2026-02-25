"""
Tests for WebSocket reconnection and session logic in main.py.

Run with: uv run pytest test_reconnection.py -v
"""
import json
import anyio
import pytest
from fastapi.testclient import TestClient

import main
from main import app, connections, player_games, lobby


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reset_state():
    """Clear all module-level state between tests."""
    connections.clear()
    player_games.clear()
    lobby.games.clear()


def recv(ws) -> dict:
    """Receive one JSON message from a TestClient WebSocket."""
    return json.loads(ws.receive_text())


def send(ws, msg: dict):
    ws.send_text(json.dumps(msg))


def drain_all(ws, window_s: float = 0.08) -> list[dict]:
    """
    Drain all messages currently buffered in the WebSocket's send stream,
    using anyio's portal and a short timeout so we never block permanently.

    Each successful receive resets the window; we stop when a `window_s`
    second window passes with no new message.
    """
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    """Reset server state before every test."""
    reset_state()
    yield
    reset_state()


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFreshConnect:
    def test_fresh_connect_receives_connected_then_lobby_state(self, client):
        """Scenario 1: fresh connection gets 'connected' then 'lobby_state'."""
        with client.websocket_connect("/ws") as ws:
            msg1 = recv(ws)
            assert msg1["type"] == "connected"
            assert "player_id" in msg1

            msg2 = recv(ws)
            assert msg2["type"] == "lobby_state"
            assert msg2["games"] == []


class TestHelloUnknownId:
    def test_hello_unknown_saved_id_gets_lobby_state(self, client):
        """Scenario 2: hello with unknown saved_id returns hello_result(restored=False) + lobby_state."""
        with client.websocket_connect("/ws") as ws:
            recv(ws)  # connected
            recv(ws)  # lobby_state

            send(ws, {"type": "hello", "saved_player_id": "nonexistent_id_abc123"})

            msg = recv(ws)
            assert msg["type"] == "hello_result"
            assert msg["restored"] is False

            msg2 = recv(ws)
            assert msg2["type"] == "lobby_state"

    def test_hello_empty_saved_id_gets_lobby_state(self, client):
        """hello with empty saved_id also returns hello_result(restored=False)."""
        with client.websocket_connect("/ws") as ws:
            recv(ws)  # connected
            recv(ws)  # lobby_state

            send(ws, {"type": "hello", "saved_player_id": ""})

            msg = recv(ws)
            assert msg["type"] == "hello_result"
            assert msg["restored"] is False


class TestReconnectWaitingGame:
    def test_player_creates_game_disconnects_reconnects(self, client):
        """Scenario 3: player creates game, disconnects, reconnects with hello - session restored."""
        with client.websocket_connect("/ws") as ws:
            original_pid = recv(ws)["player_id"]
            recv(ws)  # lobby_state

            send(ws, {"type": "create_game", "name": "Alice"})

            joined = recv(ws)
            assert joined["type"] == "joined_game"
            game_id = joined["game_id"]

            drain_all(ws)  # consume game_state + lobby_state broadcast
            # WebSocket disconnects here

        assert original_pid in player_games
        assert player_games[original_pid] == game_id
        assert original_pid not in connections

        with client.websocket_connect("/ws") as ws2:
            temp_pid = recv(ws2)["player_id"]
            recv(ws2)  # lobby_state

            send(ws2, {"type": "hello", "saved_player_id": original_pid})

            reconnected = recv(ws2)
            assert reconnected["type"] == "hello_result"
            assert reconnected["restored"] is True
            assert reconnected["player_id"] == original_pid

            game_state_msg = recv(ws2)
            assert game_state_msg["type"] == "game_state"

            assert temp_pid not in connections
            assert original_pid in connections

    def test_reconnect_restores_player_games_mapping(self, client):
        """After reconnecting, player_games maps original_pid to game_id."""
        with client.websocket_connect("/ws") as ws:
            original_pid = recv(ws)["player_id"]
            recv(ws)

            send(ws, {"type": "create_game", "name": "Bob"})
            joined = recv(ws)
            game_id = joined["game_id"]
            drain_all(ws)

        with client.websocket_connect("/ws") as ws2:
            recv(ws2)
            recv(ws2)

            send(ws2, {"type": "hello", "saved_player_id": original_pid})

            recv(ws2)  # connected
            recv(ws2)  # game_state

            assert player_games.get(original_pid) == game_id


class TestReconnectPlayingGame:
    def _create_started_game(self, client) -> tuple[str, str, str]:
        """
        Two players connect, creator starts the game.
        Returns (pid1, pid2, game_id) after both disconnect.
        """
        with client.websocket_connect("/ws") as ws1:
            pid1 = recv(ws1)["player_id"]
            recv(ws1)  # lobby_state

            send(ws1, {"type": "create_game", "name": "Alice"})
            joined1 = recv(ws1)
            assert joined1["type"] == "joined_game"
            game_id = joined1["game_id"]
            drain_all(ws1)

            with client.websocket_connect("/ws") as ws2:
                pid2 = recv(ws2)["player_id"]
                recv(ws2)  # lobby_state

                send(ws2, {"type": "join_game", "game_id": game_id, "name": "Bob"})
                drain_all(ws2)
                drain_all(ws1)

                send(ws1, {"type": "start_game"})
                drain_all(ws1)
                drain_all(ws2)
                # ws2 disconnects

            # ws1 disconnects

        return pid1, pid2, game_id

    def test_player_reconnects_during_playing_game(self, client):
        """Scenario 4: game is playing, player disconnects and reconnects."""
        pid1, pid2, game_id = self._create_started_game(client)

        assert player_games.get(pid1) == game_id
        assert player_games.get(pid2) == game_id
        assert lobby.get_game(game_id).status == "playing"

        with client.websocket_connect("/ws") as ws:
            recv(ws)
            recv(ws)  # lobby_state

            send(ws, {"type": "hello", "saved_player_id": pid1})

            reconnected = recv(ws)
            assert reconnected["type"] == "hello_result"
            assert reconnected["restored"] is True
            assert reconnected["player_id"] == pid1

            game_state_msg = recv(ws)
            assert game_state_msg["type"] == "game_state"
            assert game_state_msg["state"]["status"] == "playing"

    def test_player2_reconnects_during_playing_game(self, client):
        """Scenario 6: player2 disconnects and reconnects while game is playing."""
        pid1, pid2, game_id = self._create_started_game(client)

        with client.websocket_connect("/ws") as ws:
            recv(ws)
            recv(ws)

            send(ws, {"type": "hello", "saved_player_id": pid2})

            reconnected = recv(ws)
            assert reconnected["type"] == "hello_result"
            assert reconnected["restored"] is True
            assert reconnected["player_id"] == pid2

            game_state_msg = recv(ws)
            assert game_state_msg["type"] == "game_state"
            assert game_state_msg["state"]["status"] == "playing"

    def test_game_state_has_correct_structure(self, client):
        """Reconnected player receives properly structured game_state."""
        pid1, pid2, game_id = self._create_started_game(client)

        with client.websocket_connect("/ws") as ws:
            recv(ws)
            recv(ws)

            send(ws, {"type": "hello", "saved_player_id": pid1})
            recv(ws)  # connected
            msg = recv(ws)

            assert msg["type"] == "game_state"
            state = msg["state"]
            assert "status" in state
            assert "players" in state
            assert state["status"] == "playing"


class TestEndedGameNoRestore:
    def test_hello_with_ended_game_gets_lobby(self, client):
        """Scenario 5: saved_id points to ended game - gets lobby, no restoration."""
        with client.websocket_connect("/ws") as ws:
            pid = recv(ws)["player_id"]
            recv(ws)

            send(ws, {"type": "create_game", "name": "Carol"})
            joined = recv(ws)
            game_id = joined["game_id"]
            drain_all(ws)

            game = lobby.get_game(game_id)
            game.status = "ended"

        assert player_games.get(pid) == game_id

        with client.websocket_connect("/ws") as ws2:
            recv(ws2)
            recv(ws2)

            send(ws2, {"type": "hello", "saved_player_id": pid})

            msg = recv(ws2)
            assert msg["type"] == "hello_result"
            assert msg["restored"] is False


class TestLeaveWaitingGameRegression:
    def test_leave_waiting_game_does_not_affect_playing_games(self, client):
        """
        Scenario 7 (critical regression): leave_waiting_game must be a no-op
        when the player's game status is 'playing'.
        """
        with client.websocket_connect("/ws") as ws1:
            pid1 = recv(ws1)["player_id"]
            recv(ws1)

            send(ws1, {"type": "create_game", "name": "Dave"})
            joined1 = recv(ws1)
            game_id = joined1["game_id"]
            drain_all(ws1)

            with client.websocket_connect("/ws") as ws2:
                pid2 = recv(ws2)["player_id"]
                recv(ws2)

                send(ws2, {"type": "join_game", "game_id": game_id, "name": "Eve"})
                drain_all(ws2)
                drain_all(ws1)

                send(ws1, {"type": "start_game"})
                drain_all(ws1)
                drain_all(ws2)

                game = lobby.get_game(game_id)
                assert game.status == "playing"

                # Trying to create a game while in a playing game should fail.
                # leave_waiting_game runs first but must skip the playing game.
                send(ws1, {"type": "create_game", "name": "Dave"})
                error_msg = recv(ws1)
                assert error_msg["type"] == "error"
                assert "already in a game" in error_msg["message"].lower()

                # Playing game must be intact
                assert player_games.get(pid1) == game_id
                assert game.status == "playing"
                assert any(p["id"] == pid1 for p in game.players)

    def test_leave_waiting_game_works_for_waiting_games(self, client):
        """leave_waiting_game correctly removes a player from a waiting game."""
        with client.websocket_connect("/ws") as ws1:
            pid1 = recv(ws1)["player_id"]
            recv(ws1)

            send(ws1, {"type": "create_game", "name": "Frank"})
            joined = recv(ws1)
            game_id = joined["game_id"]
            drain_all(ws1)

            with client.websocket_connect("/ws") as ws2:
                pid2 = recv(ws2)["player_id"]
                recv(ws2)

                send(ws2, {"type": "join_game", "game_id": game_id, "name": "Grace"})
                drain_all(ws2)
                drain_all(ws1)

                # pid2 creates a new game: triggers leave_waiting_game for game_id
                send(ws2, {"type": "create_game", "name": "Grace"})
                drain_all(ws2)
                drain_all(ws1)

                original_game = lobby.get_game(game_id)
                assert original_game is not None
                assert not any(p["id"] == pid2 for p in original_game.players)
                assert player_games.get(pid2) != game_id


class TestHelloEdgeCases:
    def test_hello_no_saved_id_key_gets_hello_result_false(self, client):
        """hello message without saved_player_id key returns hello_result(restored=False)."""
        with client.websocket_connect("/ws") as ws:
            recv(ws)
            recv(ws)

            send(ws, {"type": "hello"})

            msg = recv(ws)
            assert msg["type"] == "hello_result"
            assert msg["restored"] is False

    def test_hello_with_own_pid_not_in_game_gets_hello_result_false(self, client):
        """hello with own current pid (not in any game) returns hello_result(restored=False)."""
        with client.websocket_connect("/ws") as ws:
            pid = recv(ws)["player_id"]
            recv(ws)

            send(ws, {"type": "hello", "saved_player_id": pid})

            msg = recv(ws)
            assert msg["type"] == "hello_result"
            assert msg["restored"] is False

    def test_multiple_reconnects_restore_correctly(self, client):
        """A player can reconnect more than once and always gets their session back."""
        with client.websocket_connect("/ws") as ws:
            original_pid = recv(ws)["player_id"]
            recv(ws)

            send(ws, {"type": "create_game", "name": "Henry"})
            joined = recv(ws)
            game_id = joined["game_id"]
            drain_all(ws)

        for _ in range(2):
            with client.websocket_connect("/ws") as ws:
                recv(ws)
                recv(ws)
                send(ws, {"type": "hello", "saved_player_id": original_pid})
                r = recv(ws)
                assert r["type"] == "hello_result"
                assert r["restored"] is True
                assert r["player_id"] == original_pid
                recv(ws)  # game_state

            assert player_games.get(original_pid) == game_id
