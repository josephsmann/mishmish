import uuid
from collections import Counter
from datetime import datetime, timezone
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
        self.winner_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self.ended_at: Optional[str] = None
        self.turn_number: int = 0

    def to_dict(self) -> Dict:
        return {
            "game_id": self.game_id,
            "creator_id": self.creator_id,
            "players": self.players,
            "table": self.table,
            "draw_pile": self.draw_pile,
            "current_player_idx": self.current_player_idx,
            "status": self.status,
            "winner": self.winner,
            "winner_id": self.winner_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "turn_number": self.turn_number,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Game":
        g = cls(game_id=d["game_id"], creator_id=d["creator_id"])
        g.players = d["players"]
        g.table = d["table"]
        g.draw_pile = d["draw_pile"]
        g.current_player_idx = d["current_player_idx"]
        g.status = d["status"]
        g.winner = d.get("winner")
        g.winner_id = d.get("winner_id")
        g.started_at = d.get("started_at")
        g.ended_at = d.get("ended_at")
        g.turn_number = d.get("turn_number", 0)
        return g

    def add_player(self, player_id: str, name: str, is_bot: bool = False) -> bool:
        if self.status != "waiting":
            return False
        if any(p['id'] == player_id for p in self.players):
            return False
        self.players.append({"id": player_id, "name": name, "hand": [], "is_bot": is_bot})
        return True

    def add_bot(self) -> Optional[str]:
        bot_id = "bot_" + uuid.uuid4().hex[:8]
        name = "Mish Bot"
        if not self.add_player(bot_id, name, is_bot=True):
            return None
        return bot_id

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

        # Non-dealer goes first; their first turn action is to draw or play
        self.current_player_idx = 1 % len(self.players)
        self.status = "playing"
        self.started_at = datetime.now(timezone.utc).isoformat()
        return True

    def draw_card(self, player_id: str) -> Optional[Card]:
        player = self._get_current_player()
        if player is None or player['id'] != player_id:
            return None
        if not self.draw_pile:
            # Deck exhausted - game is a draw
            self.status = "ended"
            self.winner = None
            self.winner_id = None
            self.ended_at = datetime.now(timezone.utc).isoformat()
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
            import logging as _log
            _log.getLogger("mishmish").warning(
                "play_turn remove detail: removed=%s added=%s old_table=%s new_table=%s",
                dict(cards_removed), dict(cards_added),
                [[card_key(c) for c in m] for m in self.table],
                [[card_key(c) for c in m] for m in new_table],
            )
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
            self.winner_id = player['id']
            self.ended_at = datetime.now(timezone.utc).isoformat()
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
                    "is_bot": p.get('is_bot', False),
                }
                for p in self.players
            ],
            "your_hand": next(
                (p['hand'] for p in self.players if p['id'] == player_id), []
            ),
            "table": self.table,
            "draw_pile_size": len(self.draw_pile),
            "is_creator": player_id == self.creator_id,
        }

    def _get_current_player(self) -> Optional[Dict]:
        if not self.players or self.status != "playing":
            return None
        return self.players[self.current_player_idx]

    def _advance_turn(self):
        self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
        self.turn_number += 1
