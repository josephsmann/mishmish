import random
from typing import Dict, List

RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS = ['H', 'D', 'C', 'S']

Card = Dict[str, str]


def card_key(card: Card) -> str:
    return f"{card['rank']}{card['suit']}"


def make_deck() -> List[Card]:
    deck = []
    for _ in range(2):
        for rank in RANKS:
            for suit in SUITS:
                deck.append({"rank": rank, "suit": suit})
    random.shuffle(deck)
    return deck


def is_valid_set(cards: List[Card]) -> bool:
    if len(cards) < 3:
        return False
    rank = cards[0]['rank']
    suits = [c['suit'] for c in cards]
    # All same rank
    if not all(c['rank'] == rank for c in cards):
        return False
    # All different suits (no duplicates)
    if len(suits) != len(set(suits)):
        return False
    return True


def is_valid_run(cards: List[Card]) -> bool:
    if len(cards) < 3:
        return False
    suit = cards[0]['suit']
    # All same suit
    if not all(c['suit'] == suit for c in cards):
        return False
    indices = sorted(RANKS.index(c['rank']) for c in cards)
    n = len(indices)
    # Normal consecutive check
    if indices[-1] - indices[0] == n - 1:
        return True
    # Wraparound: find the single largest gap and check if wrapping makes them consecutive
    # gaps between consecutive sorted indices, plus the wrap-around gap
    gaps = []
    for i in range(n - 1):
        gaps.append(indices[i + 1] - indices[i])
    # The wraparound gap: from last to first going around
    wrap_gap = (len(RANKS) - indices[-1]) + indices[0]
    gaps.append(wrap_gap)
    max_gap = max(gaps)
    # There should be exactly one gap > 1 (the "missing" stretch)
    if gaps.count(max_gap) != 1:
        # Only valid if all gaps == 1 (already handled above) or exactly one big gap
        if sum(1 for g in gaps if g > 1) != 1:
            return False
    # Total span must equal n (n cards consecutive)
    # With wraparound: total = len(RANKS) - max_gap
    total_span = len(RANKS) - max_gap
    return total_span == n - 1


def is_valid_meld(cards: List[Card]) -> bool:
    return is_valid_set(cards) or is_valid_run(cards)
