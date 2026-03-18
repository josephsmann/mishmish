# tests/test_bot_v3.py
import pytest
from bot import BotConfig, find_best_play


def test_botconfig_defaults():
    cfg = BotConfig()
    assert cfg.lam == 0.5
    assert cfg.hand_cutoff == 10


def test_botconfig_custom():
    cfg = BotConfig(lam=0.8, hand_cutoff=12)
    assert cfg.lam == 0.8
    assert cfg.hand_cutoff == 12


def test_find_best_play_accepts_config_kwarg():
    """find_best_play must not crash when config is passed."""
    hand = [{"rank": "A", "suit": "S"}, {"rank": "A", "suit": "H"}, {"rank": "A", "suit": "D"}]
    cfg = BotConfig()
    result = find_best_play(hand, [], version="v3", config=cfg)
    # Should return a table with the triple
    assert result is not None
    assert len(result) == 1
