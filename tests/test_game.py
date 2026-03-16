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
