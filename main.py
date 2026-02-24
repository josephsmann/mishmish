import json
import uuid
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lobby import Lobby

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

lobby = Lobby()
connections: Dict[str, WebSocket] = {}   # player_id -> WebSocket
player_games: Dict[str, str] = {}        # player_id -> game_id


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


async def send(ws: WebSocket, msg: dict):
    await ws.send_text(json.dumps(msg))


async def broadcast_game_state(game_id: str):
    game = lobby.get_game(game_id)
    if game is None:
        return
    for player in game.players:
        pid = player['id']
        ws = connections.get(pid)
        if ws:
            state = game.state_for_player(pid)
            await send(ws, {"type": "game_state", "state": state})


async def broadcast_lobby_state():
    games = lobby.list_games()
    for pid, ws in connections.items():
        if pid not in player_games:
            await send(ws, {"type": "lobby_state", "games": games})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    player_id = uuid.uuid4().hex
    connections[player_id] = ws
    await send(ws, {"type": "connected", "player_id": player_id})
    await send(ws, {"type": "lobby_state", "games": lobby.list_games()})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "create_game":
                name = msg.get("name", "Player").strip() or "Player"
                if player_id in player_games:
                    await send(ws, {"type": "error", "message": "Already in a game"})
                    continue
                game = lobby.create_game(player_id)
                game.add_player(player_id, name)
                player_games[player_id] = game.game_id
                await send(ws, {
                    "type": "joined_game",
                    "game_id": game.game_id,
                    "is_creator": True,
                })
                await broadcast_game_state(game.game_id)
                await broadcast_lobby_state()

            elif msg_type == "join_game":
                game_id = msg.get("game_id")
                name = msg.get("name", "Player").strip() or "Player"
                if player_id in player_games:
                    await send(ws, {"type": "error", "message": "Already in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None:
                    await send(ws, {"type": "error", "message": "Game not found"})
                    continue
                if not game.add_player(player_id, name):
                    await send(ws, {"type": "error", "message": "Cannot join game"})
                    continue
                player_games[player_id] = game_id
                await send(ws, {
                    "type": "joined_game",
                    "game_id": game_id,
                    "is_creator": False,
                })
                await broadcast_game_state(game_id)
                await broadcast_lobby_state()

            elif msg_type == "start_game":
                game_id = player_games.get(player_id)
                if not game_id:
                    await send(ws, {"type": "error", "message": "Not in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None or not game.start(player_id):
                    await send(ws, {"type": "error", "message": "Cannot start game"})
                    continue
                await broadcast_game_state(game_id)
                await broadcast_lobby_state()

            elif msg_type == "draw_card":
                game_id = player_games.get(player_id)
                if not game_id:
                    await send(ws, {"type": "error", "message": "Not in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None:
                    continue
                result = game.draw_card(player_id)
                if result is None and game.status != "ended":
                    await send(ws, {"type": "error", "message": "Not your turn or empty deck"})
                    continue
                await broadcast_game_state(game_id)

            elif msg_type == "play_turn":
                game_id = player_games.get(player_id)
                if not game_id:
                    await send(ws, {"type": "error", "message": "Not in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None:
                    continue
                new_table = msg.get("table", [])
                ok, reason = game.play_turn(player_id, new_table)
                if not ok:
                    await send(ws, {"type": "error", "message": reason})
                    continue
                await broadcast_game_state(game_id)

            else:
                await send(ws, {"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        connections.pop(player_id, None)
        game_id = player_games.pop(player_id, None)
        if game_id:
            game = lobby.get_game(game_id)
            if game:
                # Remove player from game
                game.players = [p for p in game.players if p['id'] != player_id]
                if not game.players:
                    lobby.remove_game(game_id)
                elif game.creator_id == player_id and game.players:
                    # Transfer creator
                    game.creator_id = game.players[0]['id']
                    if game.status == "playing":
                        # Adjust current player index
                        game.current_player_idx = game.current_player_idx % len(game.players)
                    await broadcast_game_state(game_id)
        await broadcast_lobby_state()
