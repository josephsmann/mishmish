"""Tests for Game data model changes."""
import pytest
from game import Game


def test_bot_timeout_seconds_default():
    g = Game(game_id="g1", creator_id="p1")
    assert g.bot_timeout_seconds == 10.0


def test_bot_timeout_seconds_survives_round_trip():
    g = Game(game_id="g1", creator_id="p1")
    g.bot_timeout_seconds = 25.0
    g2 = Game.from_dict(g.to_dict())
    assert g2.bot_timeout_seconds == 25.0


def test_bot_timeout_seconds_defaults_on_missing_key():
    """Old serialized games without the key should default to 10.0."""
    g = Game(game_id="g1", creator_id="p1")
    d = g.to_dict()
    del d["bot_timeout_seconds"]
    g2 = Game.from_dict(d)
    assert g2.bot_timeout_seconds == 10.0


def _make_started_game():
    g = Game("g1", "p1")
    g.add_player("p1", "Alice")
    g.add_player("p2", "Bob")
    assert g.start("p1")
    return g


def test_state_for_player_includes_last_activity():
    g = _make_started_game()
    state = g.state_for_player("p1")
    assert state["last_activity"] == g.last_activity
    assert isinstance(state["last_activity"], str)


def test_last_activity_updates_on_draw():
    g = _make_started_game()
    before = g.last_activity
    import time
    time.sleep(0.01)
    current = g._get_current_player()["id"]
    g.draw_card(current)
    assert g.state_for_player("p1")["last_activity"] > before
