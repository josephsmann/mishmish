import json
import uuid
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from lobby import Lobby

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/static/{filename:path}")
async def static_files(filename: str):
    file_path = STATIC_DIR / filename
    if not file_path.exists():
        return Response(status_code=404)
    response = FileResponse(file_path)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

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
    # Use a mutable container so the reconnect handler can update the id
    pid = [uuid.uuid4().hex]
    connections[pid[0]] = ws
    await send(ws, {"type": "connected", "player_id": pid[0]})
    await send(ws, {"type": "lobby_state", "games": lobby.list_games()})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")
            player_id = pid[0]

            if msg_type == "hello":
                # Reconnect: restore previous session if it still exists
                saved_id = msg.get("saved_player_id", "")
                if saved_id and saved_id in player_games:
                    connections.pop(player_id, None)
                    pid[0] = saved_id
                    connections[saved_id] = ws
                    await send(ws, {"type": "connected", "player_id": saved_id})
                    game_id = player_games[saved_id]
                    await broadcast_game_state(game_id)
                else:
                    await send(ws, {"type": "lobby_state", "games": lobby.list_games()})

            elif msg_type == "create_game":
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
        player_id = pid[0]
        connections.pop(player_id, None)
        # Keep player_games intact so the player can reconnect mid-game.
        # Only clean up if the game is still in the waiting lobby (not started).
        game_id = player_games.get(player_id)
        if game_id:
            game = lobby.get_game(game_id)
            if game and game.status == "waiting":
                game.players = [p for p in game.players if p['id'] != player_id]
                player_games.pop(player_id, None)
                if not game.players:
                    lobby.remove_game(game_id)
                else:
                    if game.creator_id == player_id:
                        game.creator_id = game.players[0]['id']
                    await broadcast_game_state(game_id)
        await broadcast_lobby_state()
