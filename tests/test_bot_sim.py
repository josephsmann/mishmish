import pytest
from bot import BotConfig
from bot_sim import simulate_game


def test_simulate_game_returns_valid_outcome():
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    result = simulate_game(cfg, cfg)
    assert result in ("a", "b", "draw")


def test_simulate_game_completes_without_hanging():
    """Game must complete within a reasonable time (no infinite loops)."""
    import time
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    start = time.time()
    simulate_game(cfg, cfg)
    elapsed = time.time() - start
    assert elapsed < 10.0, f"Game took too long: {elapsed:.1f}s"


def test_simulate_game_symmetric():
    """Running many games should not always return the same winner (non-degenerate)."""
    cfg = BotConfig(lam=0.5, hand_cutoff=10)
    results = [simulate_game(cfg, cfg) for _ in range(20)]
    assert len(set(results)) > 1


def test_simulate_game_different_configs():
    """Two configs can be compared — just check it runs cleanly."""
    cfg_a = BotConfig(lam=0.0, hand_cutoff=6)
    cfg_b = BotConfig(lam=1.0, hand_cutoff=14)
    result = simulate_game(cfg_a, cfg_b)
    assert result in ("a", "b", "draw")


def test_simulate_game_terminates_on_deck_exhaustion(monkeypatch):
    """simulate_game terminates when the deck runs out."""
    import game as game_module
    from unittest.mock import patch

    original_make_deck = game_module.make_deck

    def tiny_deck():
        # Return just enough cards to deal 9 each (18 cards) but nothing left to draw
        return original_make_deck()[:18]

    with patch.object(game_module, "make_deck", tiny_deck):
        cfg = BotConfig(lam=0.5, hand_cutoff=10)
        result = simulate_game(cfg, cfg)
        assert result in ("a", "b", "draw")
