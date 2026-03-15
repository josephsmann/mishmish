"""
Tests for the Mish Bot exact-cover search (bot.py).

Each test calls find_best_play(hand, table) and verifies:
  - The returned table is a valid rearrangement of table + played cards
  - The number of cards played is optimal
  - Timing is acceptable for large/duplicate-heavy states
"""

import json
import time
from collections import Counter
from pathlib import Path
from typing import List

import pytest

from deck import is_valid_meld
from bot import find_best_play


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def c(rank: str, suit: str) -> dict:
    return {"rank": rank, "suit": suit}


def card_key(card: dict) -> str:
    return card["rank"] + card["suit"]


def cards_played(hand, result_table, original_table) -> int:
    """How many hand cards ended up on the table."""
    orig_keys = Counter(card_key(c) for meld in original_table for c in meld)
    new_keys  = Counter(card_key(c) for meld in result_table  for c in meld)
    added = new_keys - orig_keys
    return sum(added.values())


def assert_valid_result(hand, table, result):
    """Shared invariant checks for any non-None result."""
    # Every meld must be valid
    for meld in result:
        assert meld, "Empty meld in result"
        assert is_valid_meld(meld), f"Invalid meld: {[card_key(c) for c in meld]}"

    # Table cards preserved + only hand cards added
    orig_keys = Counter(card_key(c) for meld in table  for c in meld)
    new_keys  = Counter(card_key(c) for meld in result for c in meld)
    added = new_keys - orig_keys
    removed = orig_keys - new_keys
    assert not removed, f"Cards removed from table: {dict(removed)}"

    hand_keys = Counter(card_key(c) for c in hand)
    missing = added - hand_keys
    assert not missing, f"Cards added that aren't in hand: {dict(missing)}"


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

def test_empty_hand_empty_table():
    assert find_best_play([], []) is None


def test_empty_table_no_meld_possible():
    hand = [c("2", "H"), c("5", "D"), c("K", "C")]
    assert find_best_play(hand, []) is None


def test_empty_table_forms_set():
    hand = [c("7", "H"), c("7", "D"), c("7", "C")]
    result = find_best_play(hand, [])
    assert result is not None
    assert_valid_result(hand, [], result)
    assert cards_played(hand, result, []) == 3


def test_empty_table_forms_run():
    hand = [c("4", "S"), c("5", "S"), c("6", "S")]
    result = find_best_play(hand, [])
    assert result is not None
    assert_valid_result(hand, [], result)
    assert cards_played(hand, result, []) == 3


def test_no_valid_play_draws():
    # Hand has no valid meld and table is empty
    hand = [c("2", "H"), c("4", "D"), c("K", "C"), c("8", "S")]
    assert find_best_play(hand, []) is None


def test_extends_existing_set():
    table = [[c("J", "H"), c("J", "D"), c("J", "C")]]
    hand  = [c("J", "S"), c("2", "H")]
    result = find_best_play(hand, table)
    assert result is not None
    assert_valid_result(hand, table, result)
    assert cards_played(hand, result, table) == 1


def test_extends_existing_run():
    table = [[c("5", "H"), c("6", "H"), c("7", "H")]]
    hand  = [c("8", "H"), c("K", "D")]
    result = find_best_play(hand, table)
    assert result is not None
    assert_valid_result(hand, table, result)
    assert cards_played(hand, result, table) == 1


def test_cannot_play_returns_none():
    table = [[c("5", "H"), c("6", "H"), c("7", "H")]]
    hand  = [c("2", "D"), c("9", "S")]
    assert find_best_play(hand, table) is None


# ---------------------------------------------------------------------------
# Meld splitting
# ---------------------------------------------------------------------------

def test_splits_run_to_insert_card():
    # Table: 2H 3H 4H 5H 6H — hand has 4H; can split into 2H3H4H + 4H5H6H
    table = [[c("2", "H"), c("3", "H"), c("4", "H"), c("5", "H"), c("6", "H")]]
    hand  = [c("4", "H")]
    result = find_best_play(hand, table)
    assert result is not None
    assert_valid_result(hand, table, result)
    assert cards_played(hand, result, table) == 1
    # Should produce two melds
    assert len(result) == 2


def test_maximises_cards_played():
    # v1 greedily plays all 4 cards; v2 may withhold Q♠ to avoid extending
    # the table run (which gifts the opponent a longer sequence).
    table = [[c("9", "S"), c("10", "S"), c("J", "S")]]
    hand  = [c("Q", "S"), c("5", "H"), c("5", "D"), c("5", "C")]
    result = find_best_play(hand, table, version="v1")
    assert result is not None
    assert_valid_result(hand, table, result)
    assert cards_played(hand, result, table) == 4


def test_prefers_playing_over_drawing():
    # Simple: bot can play 3 cards; should not return None
    table = [[c("K", "H"), c("K", "D"), c("K", "C")]]
    hand  = [c("K", "S"), c("2", "D")]
    result = find_best_play(hand, table)
    assert result is not None
    assert cards_played(hand, result, table) >= 1


# ---------------------------------------------------------------------------
# Wraparound runs
# ---------------------------------------------------------------------------

def test_wraparound_run_QKA():
    hand = [c("Q", "S"), c("K", "S"), c("A", "S")]
    result = find_best_play(hand, [])
    assert result is not None
    assert_valid_result(hand, [], result)
    assert cards_played(hand, result, []) == 3


def test_wraparound_run_A23():
    hand = [c("A", "D"), c("2", "D"), c("3", "D")]
    result = find_best_play(hand, [])
    assert result is not None
    assert_valid_result(hand, [], result)
    assert cards_played(hand, result, []) == 3


# ---------------------------------------------------------------------------
# Duplicate cards (2-deck game)
# ---------------------------------------------------------------------------

def test_duplicate_suit_cards_in_set():
    # Two copies of the same card in a set is invalid — bot should find the
    # valid 3-card set using distinct suits
    hand = [c("8", "H"), c("8", "H"), c("8", "D"), c("8", "C")]
    result = find_best_play(hand, [])
    assert result is not None
    assert_valid_result(hand, [], result)
    # At least 3 cards played
    assert cards_played(hand, result, []) >= 3


def test_duplicate_table_cards_correctness():
    # Table has two identical melds — both must be covered exactly
    table = [
        [c("3", "H"), c("3", "D"), c("3", "C")],
        [c("3", "H"), c("3", "D"), c("3", "C")],
    ]
    hand = [c("3", "S")]
    result = find_best_play(hand, table)
    # Bot may or may not be able to play, but if it does the result must be valid
    if result is not None:
        assert_valid_result(hand, table, result)


def test_duplicate_heavy_table_performance():
    """
    Reproduces the real-game hang: 45 table cards with many duplicate
    rank+suit pairs and 5 bot hand cards. Must complete in under 3 seconds.
    """
    game_turns_path = Path(__file__).parent.parent / "game_turns.json"
    if not game_turns_path.exists():
        pytest.skip("game_turns.json not present")

    turns = json.loads(game_turns_path.read_text())
    last = turns[-1]
    hand  = last["hands"]["Mish Bot"]
    table = last["table"]

    t0 = time.time()
    result = find_best_play(hand, table)
    elapsed = time.time() - t0

    assert elapsed < 3.0, f"find_best_play took {elapsed:.1f}s — too slow"
    if result is not None:
        assert_valid_result(hand, table, result)


def test_all_bot_play_turns_from_game_log():
    """
    For every turn in game_turns.json where the bot actually played cards,
    verify find_best_play finds a play (not None) on the state just before
    that turn, and that the result is valid.
    """
    game_turns_path = Path(__file__).parent.parent / "game_turns.json"
    if not game_turns_path.exists():
        pytest.skip("game_turns.json not present")

    turns = json.loads(game_turns_path.read_text())
    for i, t in enumerate(turns):
        if t["player_name"] != "Mish Bot" or t["action"] != "play":
            continue
        if i == 0:
            continue
        prev = turns[i - 1]
        hand  = prev["hands"]["Mish Bot"]
        table = prev["table"]
        result = find_best_play(hand, table)
        assert result is not None, f"Bot should have played on turn {t['turn_number']} but got None"
        assert_valid_result(hand, table, result)
        assert cards_played(hand, result, table) > 0
