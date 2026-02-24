import uuid
from collections import Counter
from typing import Dict, List, Optional, Tuple

from deck import Card, card_key, is_valid_meld, make_deck


class Game:
    def __init__(self, game_id: str, creator_id: str):
        self.game_id = game_id
        self.creator_id = creator_id
        self.players: List[Dict] = []
        self.table: List[List[Card]] = []
        self.draw_pile: List[Card] = []
        self.current_player_idx: int = 0
        self.status: str = "waiting"
        self.winner: Optional[str] = None

    def add_player(self, player_id: str, name: str) -> bool:
        if self.status != "waiting":
            return False
        if any(p['id'] == player_id for p in self.players):
            return False
        self.players.append({"id": player_id, "name": name, "hand": []})
        return True

    def start(self, requestor_id: str) -> bool:
        if requestor_id != self.creator_id:
            return False
        if self.status != "waiting":
            return False
        if len(self.players) < 2:
            return False

        self.draw_pile = make_deck()
        # Deal 9 cards to each player
        for player in self.players:
            player['hand'] = [self.draw_pile.pop() for _ in range(9)]

        # Non-dealer (index 1+) gets 1 extra card; first non-dealer is index 1
        # The non-dealer starts with 10 cards; dealer starts with 9
        # Player at index 1 (non-dealer) draws extra card
        non_dealer_idx = 1 % len(self.players)
        self.players[non_dealer_idx]['hand'].append(self.draw_pile.pop())

        # Non-dealer goes first
        self.current_player_idx = non_dealer_idx
        self.status = "playing"
        return True

    def draw_card(self, player_id: str) -> Optional[Card]:
        player = self._get_current_player()
        if player is None or player['id'] != player_id:
            return None
        if not self.draw_pile:
            # Deck exhausted - game is a draw
            self.status = "ended"
            self.winner = None
            return None
        card = self.draw_pile.pop()
        player['hand'].append(card)
        self._advance_turn()
        return card

    def play_turn(self, player_id: str, new_table: List[List[Card]]) -> Tuple[bool, str]:
        player = self._get_current_player()
        if player is None or player['id'] != player_id:
            return False, "Not your turn"

        # Validate all melds
        for meld in new_table:
            if not meld:
                return False, "Empty meld on table"
            if not is_valid_meld(meld):
                return False, f"Invalid meld: {[card_key(c) for c in meld]}"

        # Use Counter multiset to find what was added vs removed
        old_keys = Counter(card_key(c) for meld in self.table for c in meld)
        new_keys = Counter(card_key(c) for meld in new_table for c in meld)

        cards_added = new_keys - old_keys
        cards_removed = old_keys - new_keys

        if cards_removed:
            return False, "Cannot remove cards from table"
        if not cards_added:
            return False, "Must play at least one card"

        # Verify added cards are in player's hand
        hand_keys = Counter(card_key(c) for c in player['hand'])
        missing = cards_added - hand_keys
        if missing:
            return False, f"Card(s) not in hand: {list(missing.keys())}"

        # Apply changes
        # Remove played cards from hand
        remaining = list(player['hand'])
        for key, count in cards_added.items():
            removed = 0
            new_remaining = []
            for c in remaining:
                if card_key(c) == key and removed < count:
                    removed += 1
                else:
                    new_remaining.append(c)
            remaining = new_remaining
        player['hand'] = remaining
        self.table = new_table

        # Check win condition
        if not player['hand']:
            self.status = "ended"
            self.winner = player['name']
            return True, "win"

        self._advance_turn()
        return True, "ok"

    def state_for_player(self, player_id: str) -> Dict:
        current = self._get_current_player()
        return {
            "game_id": self.game_id,
            "status": self.status,
            "winner": self.winner,
            "your_turn": current is not None and current['id'] == player_id,
            "current_player_name": current['name'] if current else None,
            "players": [
                {
                    "id": p['id'],
                    "name": p['name'],
                    "hand_size": len(p['hand']),
                    "is_current": p['id'] == (current['id'] if current else None),
                }
                for p in self.players
            ],
            "your_hand": next(
                (p['hand'] for p in self.players if p['id'] == player_id), []
            ),
            "table": self.table,
            "draw_pile_size": len(self.draw_pile),
        }

    def _get_current_player(self) -> Optional[Dict]:
        if not self.players or self.status != "playing":
            return None
        return self.players[self.current_player_idx]

    def _advance_turn(self):
        self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
