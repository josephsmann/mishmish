import uuid
from typing import Dict, List, Optional

from game import Game


class Lobby:
    def __init__(self):
        self.games: Dict[str, Game] = {}

    def create_game(self, creator_id: str) -> Game:
        game_id = uuid.uuid4().hex[:8]
        game = Game(game_id=game_id, creator_id=creator_id)
        self.games[game_id] = game
        return game

    def get_game(self, game_id: str) -> Optional[Game]:
        return self.games.get(game_id)

    def list_games(self) -> List[Dict]:
        result = []
        for game in self.games.values():
            if game.status in ("waiting", "playing"):
                result.append({
                    "game_id": game.game_id,
                    "status": game.status,
                    "player_count": len(game.players),
                    "players": [p['name'] for p in game.players],
                })
        return result

    def remove_game(self, game_id: str):
        self.games.pop(game_id, None)
