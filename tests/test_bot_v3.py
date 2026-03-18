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


def c(rank, suit):
    return {"rank": rank, "suit": suit}


def test_v3_below_cutoff_uses_full_backtracking():
    """With a small hand (≤ cutoff), v3 should find the same result as v2."""
    hand = [c("A","S"), c("A","H"), c("A","D")]
    cfg = BotConfig(hand_cutoff=10)  # hand size 3 < 10 → full backtracking
    result_v2 = find_best_play(hand, [], version="v2")
    result_v3 = find_best_play(hand, [], version="v3", config=cfg)
    assert result_v3 is not None
    assert len(result_v3) == 1
    assert len(result_v3[0]) == 3


def test_v3_above_cutoff_uses_greedy_fallback():
    """With a large hand (> cutoff), v3 must still return a valid play."""
    hand = [
        c("A","S"), c("A","H"), c("A","D"),  # valid triple
        c("2","S"), c("3","H"), c("4","D"), c("5","C"),
        c("7","S"), c("8","H"), c("9","D"), c("10","C"),
    ]
    cfg = BotConfig(lam=0.5, hand_cutoff=5)  # hand size 11 > 5 → greedy
    result = find_best_play(hand, [], version="v3", config=cfg)
    assert result is not None
    assert len(result) >= 1


def test_v3_returns_none_when_no_valid_play():
    """With a large hand and no valid melds, v3 returns None."""
    hand = [c("2","S"), c("4","H"), c("7","D"), c("J","C"),
            c("3","S"), c("9","H"), c("K","D"), c("5","C"),
            c("6","S"), c("8","H"), c("Q","D")]
    cfg = BotConfig(lam=0.5, hand_cutoff=5)  # greedy path
    result = find_best_play(hand, [], version="v3", config=cfg)
    assert result is None


def test_v3_greedy_produces_valid_melds():
    """All melds returned by v3 greedy must be valid."""
    from deck import is_valid_meld
    hand = [
        c("5","S"), c("5","H"), c("5","D"), c("5","C"),
        c("6","S"), c("6","H"), c("6","D"),
        c("7","S"), c("7","H"), c("7","D"), c("7","C"),
    ]
    cfg = BotConfig(lam=0.0, hand_cutoff=5)  # greedy, no opportunity penalty
    result = find_best_play(hand, [], version="v3", config=cfg)
    assert result is not None
    for meld in result:
        assert is_valid_meld(meld), f"Invalid meld: {meld}"
