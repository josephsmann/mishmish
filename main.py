import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Header
from fastapi.responses import FileResponse, Response, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from bot import find_best_play
from lobby import Lobby
import auth
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("mishmish")

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    await auth.init_db()
    await db.init_game_tables()
    # Restore in-progress games that survived a machine restart
    for game in await db.load_active_games():
        lobby.games[game.game_id] = game
        for p in game.players:
            player_games[p["id"]] = game.game_id


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
    response = FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# ---------------------------------------------------------------------------
# Auth HTTP endpoints
# ---------------------------------------------------------------------------

def _json_error(message: str, status: int = 400):
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _json_ok(data: dict):
    return JSONResponse({"ok": True, **data})


@app.post("/auth/register")
async def register(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    phone_raw = (body.get("phone") or "").strip()

    if not username or len(username) < 2:
        return _json_error("Username must be at least 2 characters")
    if len(username) > 20:
        return _json_error("Username must be at most 20 characters")
    if len(password) < 6:
        return _json_error("Password must be at least 6 characters")

    phone = auth.normalize_phone(phone_raw) if phone_raw else None

    try:
        user = await auth.create_user(username, password, phone)
    except ValueError as e:
        return _json_error(str(e))

    token = auth.create_token(user["id"], user["username"])
    return _json_ok({"token": token, "username": user["username"], "player_id": user["id"]})


@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    user = await auth.verify_password(username, password)
    if user is None:
        return _json_error("Invalid username or password", status=401)

    token = auth.create_token(user["id"], user["username"])
    return _json_ok({"token": token, "username": user["username"], "player_id": user["id"]})


@app.post("/auth/forgot")
async def forgot_password(request: Request):
    body = await request.json()
    phone_raw = (body.get("phone") or "").strip()
    if not phone_raw:
        return _json_error("Phone number is required")

    phone = auth.normalize_phone(phone_raw)
    user = await auth.get_user_by_phone(phone)

    import os, logging
    sms_configured = bool(os.environ.get("TWILIO_FROM_NUMBER"))

    reset_link = None
    if user:
        reset_token = await auth.create_reset_token(user["id"])
        try:
            await auth.send_reset_sms(phone, reset_token)
        except Exception as e:
            logging.warning(f"SMS send failed: {e}")
        # In dev mode (no SMS number configured), surface the link directly
        if not sms_configured:
            reset_link = f"{auth.APP_BASE_URL}/reset-password?token={reset_token}"

    if reset_link:
        return _json_ok({"message": "SMS not configured — use this link to reset:", "reset_link": reset_link})
    return _json_ok({"message": "If that number is registered, a reset link has been sent."})


@app.get("/history/games")
async def history_games(limit: int = 20, offset: int = 0):
    limit = min(limit, 100)
    games = await db.get_recent_games(limit=limit, offset=offset)
    return _json_ok({"games": games})


@app.get("/history/games/{game_id}")
async def history_game_detail(game_id: str):
    game = await db.get_game_detail(game_id)
    if game is None:
        return _json_error("Game not found", status=404)
    return _json_ok({"game": game})


@app.get("/history/players/{player_id}/games")
async def history_player_games(player_id: str, limit: int = 20, offset: int = 0):
    limit = min(limit, 100)
    games = await db.get_games_for_player(player_id=player_id, limit=limit, offset=offset)
    return _json_ok({"games": games})


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

def _check_admin(x_admin_key: str | None) -> bool:
    admin_key = os.environ.get("ADMIN_KEY", "")
    return bool(admin_key and x_admin_key == admin_key)


@app.get("/admin/games")
async def admin_list_games(x_admin_key: str | None = Header(default=None)):
    """List all active in-memory games with player names and status."""
    if not _check_admin(x_admin_key):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    games = [
        {
            "game_id": g.game_id,
            "status": g.status,
            "players": [p["name"] for p in g.players],
        }
        for g in lobby.games.values()
    ]
    return _json_ok({"games": games, "count": len(games)})


@app.delete("/admin/games/{game_id}")
async def admin_delete_game(game_id: str, x_admin_key: str | None = Header(default=None)):
    """Delete a specific game by ID."""
    if not _check_admin(x_admin_key):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    game = lobby.get_game(game_id)
    if game is None:
        return _json_error("Game not found", status=404)
    for p in game.players:
        player_games.pop(p["id"], None)
        ws_p = connections.get(p["id"])
        if ws_p:
            await send(ws_p, {"type": "game_aborted", "message": "Game removed by admin", "reason": "other"})
    lobby.remove_game(game_id)
    try:
        await db.delete_active_game(game_id)
    except Exception as exc:
        log.warning("admin_delete_game: DB cleanup failed for %s: %s", game_id, exc)
    log.info("admin_delete_game: deleted game=%s", game_id)
    await broadcast_lobby_state()
    return _json_ok({"deleted": game_id})


@app.delete("/admin/games")
async def admin_delete_all_games(x_admin_key: str | None = Header(default=None)):
    """Delete all active games (useful for clearing out test games)."""
    if not _check_admin(x_admin_key):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    game_ids = list(lobby.games.keys())
    for game_id in game_ids:
        game = lobby.get_game(game_id)
        if game is None:
            continue
        for p in game.players:
            player_games.pop(p["id"], None)
            ws_p = connections.get(p["id"])
            if ws_p:
                await send(ws_p, {"type": "game_aborted", "message": "Game removed by admin", "reason": "other"})
        lobby.remove_game(game_id)
        try:
            await db.delete_active_game(game_id)
        except Exception as exc:
            log.warning("admin_delete_all_games: DB cleanup failed for %s: %s", game_id, exc)
    log.info("admin_delete_all_games: deleted %d games", len(game_ids))
    await broadcast_lobby_state()
    return _json_ok({"deleted": game_ids, "count": len(game_ids)})


@app.get("/reset-password")
async def reset_password_page(token: str = ""):
    """Serve the SPA; the frontend handles the token from the query string."""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/auth/reset")
async def reset_password(request: Request):
    body = await request.json()
    token = (body.get("token") or "").strip()
    new_password = body.get("password") or ""

    if len(new_password) < 6:
        return _json_error("Password must be at least 6 characters")

    user_id = await auth.consume_reset_token(token)
    if user_id is None:
        return _json_error("Reset link is invalid or has expired", status=400)

    await auth.update_password(user_id, new_password)
    user = await auth.get_user_by_id(user_id)
    new_jwt = auth.create_token(user_id, user["username"])
    return _json_ok({"token": new_jwt, "username": user["username"], "player_id": user_id})


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

async def send(ws: WebSocket, msg: dict) -> bool:
    """Send a message; returns False and logs if the send fails."""
    try:
        await ws.send_text(json.dumps(msg))
        return True
    except Exception as exc:
        log.warning("send failed (type=%s): %s", msg.get("type"), exc)
        return False


async def broadcast_game_state(game_id: str):
    game = lobby.get_game(game_id)
    if game is None:
        log.warning("broadcast_game_state: game %s not found", game_id)
        return
    # Persist state on every change so a restart can resume in-progress games
    if game.status in ("waiting", "playing"):
        await db.save_active_game(game)
    current = game._get_current_player()
    current_id = current["id"] if current else None
    for player in list(game.players):
        pid = player['id']
        ws = connections.get(pid)
        if ws:
            state = game.state_for_player(pid)
            ok = await send(ws, {"type": "game_state", "state": state})
            if not ok:
                log.warning(
                    "broadcast_game_state: failed to send to player %s (game %s, their_turn=%s)",
                    pid, game_id, pid == current_id,
                )
                # Remove the dead socket so future broadcasts skip it cleanly
                connections.pop(pid, None)
        else:
            log.info(
                "broadcast_game_state: player %s has no connection (game %s, their_turn=%s)",
                pid, game_id, pid == current_id,
            )


async def leave_waiting_game(player_id: str):
    """Remove player from their current game if it hasn't started yet."""
    old_game_id = player_games.get(player_id)
    if not old_game_id:
        return
    old_game = lobby.get_game(old_game_id)
    if not old_game or old_game.status != "waiting":
        return
    old_game.players = [p for p in old_game.players if p['id'] != player_id]
    player_games.pop(player_id, None)
    if not old_game.players:
        lobby.remove_game(old_game_id)
    else:
        if old_game.creator_id == player_id:
            old_game.creator_id = old_game.players[0]['id']
        await broadcast_game_state(old_game_id)


async def cleanup_ended_game(game_id: str):
    game = lobby.get_game(game_id)
    if game and game.status == "ended":
        for p in game.players:
            player_games.pop(p['id'], None)
        lobby.remove_game(game_id)
        try:
            await db.record_game_end(game, "ended")
            await db.delete_active_game(game_id)
        except Exception as exc:
            log.error("cleanup_ended_game: DB persist failed for game=%s: %s", game_id, exc)


async def trigger_bot_if_needed(game_id: str):
    game = lobby.get_game(game_id)
    if game is None or game.status != "playing":
        return
    current = game._get_current_player()
    if current is None or not current.get('is_bot'):
        return

    bot_id = current['id']
    log.info("bot turn: bot=%s game=%s", bot_id, game_id)
    await asyncio.sleep(0.8)

    # Re-check after sleep
    game = lobby.get_game(game_id)
    if game is None or game.status != "playing":
        return
    current = game._get_current_player()
    if current is None or current['id'] != bot_id:
        return

    new_table = find_best_play(current['hand'], game.table)
    if new_table is None:
        log.info("bot draw_card: bot=%s game=%s", bot_id, game_id)
        game.draw_card(bot_id)
    else:
        ok, _ = game.play_turn(bot_id, new_table)
        if not ok:
            log.warning("bot play_turn failed, drawing: bot=%s game=%s", bot_id, game_id)
            game.draw_card(bot_id)
        else:
            log.info("bot play_turn ok: bot=%s game=%s", bot_id, game_id)

    await broadcast_game_state(game_id)
    await cleanup_ended_game(game_id)
    await trigger_bot_if_needed(game_id)


async def broadcast_lobby_state():
    games = lobby.list_games()
    for pid, ws in list(connections.items()):
        if pid not in player_games:
            await send(ws, {"type": "lobby_state", "games": games})


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Use a mutable container so the reconnect handler can update the id
    pid = [uuid.uuid4().hex]
    connections[pid[0]] = ws
    log.info("ws connect: tmp_pid=%s total_connections=%d", pid[0], len(connections))
    await send(ws, {"type": "connected", "player_id": pid[0]})
    await send(ws, {"type": "lobby_state", "games": lobby.list_games()})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")
            player_id = pid[0]

            if msg_type == "hello":
                # --- JWT-authenticated session (registered players) ---
                auth_token = msg.get("auth_token", "")
                if auth_token:
                    payload = auth.decode_token(auth_token)
                    if payload:
                        account_id = payload["sub"]
                        username = payload["username"]
                        log.info("hello jwt: tmp=%s -> account=%s username=%s", player_id, account_id, username)
                        # Switch the connection to the persistent account id
                        connections.pop(player_id, None)
                        pid[0] = account_id
                        connections[account_id] = ws
                        # Restore in-progress game if any
                        game_id = player_games.get(account_id)
                        game = lobby.get_game(game_id) if game_id else None
                        if game and game.status in ("waiting", "playing"):
                            await send(ws, {
                                "type": "hello_result",
                                "restored": True,
                                "player_id": account_id,
                                "username": username,
                            })
                            await broadcast_game_state(game_id)
                            if game.status == "waiting":
                                await broadcast_lobby_state()
                        else:
                            await send(ws, {
                                "type": "hello_result",
                                "restored": False,
                                "player_id": account_id,
                                "username": username,
                            })
                            await send(ws, {"type": "lobby_state", "games": lobby.list_games()})
                        continue

                # --- Legacy: ephemeral saved_player_id (guests) ---
                saved_id = msg.get("saved_player_id", "")
                game_id = player_games.get(saved_id)
                game = lobby.get_game(game_id) if game_id else None
                if saved_id and game and game.status in ("waiting", "playing"):
                    connections.pop(player_id, None)
                    pid[0] = saved_id
                    connections[saved_id] = ws
                    await send(ws, {"type": "hello_result", "restored": True, "player_id": saved_id})
                    await broadcast_game_state(game_id)
                    if game.status == "waiting":
                        await broadcast_lobby_state()
                else:
                    await send(ws, {"type": "hello_result", "restored": False})
                    await send(ws, {"type": "lobby_state", "games": lobby.list_games()})

            elif msg_type == "create_game":
                name = msg.get("name", "Player").strip() or "Player"
                await leave_waiting_game(player_id)
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
                await leave_waiting_game(player_id)
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
                await trigger_bot_if_needed(game_id)

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
                    log.warning("draw_card rejected: pid=%s game=%s", player_id, game_id)
                    await send(ws, {"type": "error", "message": "Not your turn or empty deck"})
                    continue
                log.info("draw_card: pid=%s game=%s status=%s", player_id, game_id, game.status)
                await broadcast_game_state(game_id)
                await cleanup_ended_game(game_id)
                await trigger_bot_if_needed(game_id)

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
                    log.warning("play_turn rejected: pid=%s game=%s reason=%s", player_id, game_id, reason)
                    await send(ws, {"type": "error", "message": reason})
                    continue
                log.info("play_turn ok: pid=%s game=%s status=%s", player_id, game_id, game.status)
                await broadcast_game_state(game_id)
                await cleanup_ended_game(game_id)
                await trigger_bot_if_needed(game_id)

            elif msg_type == "add_bot":
                game_id = player_games.get(player_id)
                if not game_id:
                    await send(ws, {"type": "error", "message": "Not in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None or game.creator_id != player_id:
                    await send(ws, {"type": "error", "message": "Only the creator can add a bot"})
                    continue
                bot_id = game.add_bot()
                if bot_id is None:
                    await send(ws, {"type": "error", "message": "Cannot add bot"})
                    continue
                await broadcast_game_state(game_id)
                await broadcast_lobby_state()

            elif msg_type == "stage_update":
                game_id = player_games.get(player_id)
                if not game_id:
                    continue
                game = lobby.get_game(game_id)
                if game is None:
                    continue
                current = game._get_current_player()
                if current is None or current['id'] != player_id:
                    continue
                staged_table = msg.get("table", [])
                staged_hand_size = msg.get("hand_size")
                for p in game.players:
                    if p['id'] == player_id:
                        continue
                    ws_p = connections.get(p['id'])
                    if ws_p:
                        await send(ws_p, {"type": "table_preview", "table": staged_table, "hand_size": staged_hand_size})

            elif msg_type == "abort_game":
                game_id = player_games.get(player_id)
                if not game_id:
                    log.warning("abort_game: pid=%s has no game", player_id)
                    await send(ws, {"type": "error", "message": "Not in a game"})
                    continue
                game = lobby.get_game(game_id)
                if game is None or game.status == "ended":
                    log.warning("abort_game: game %s not found or already ended (pid=%s)", game_id, player_id)
                    await send(ws, {"type": "error", "message": "No active game to abort"})
                    continue
                log.info("abort_game: pid=%s aborting game=%s status=%s", player_id, game_id, game.status)
                # Clean up in-memory state first (never fails)
                for p in game.players:
                    player_games.pop(p['id'], None)
                lobby.remove_game(game_id)
                # Notify all players; the aborter gets reason="self", others get reason="other"
                for p in game.players:
                    ws_p = connections.get(p['id'])
                    if ws_p:
                        reason = "self" if p['id'] == player_id else "other"
                        await send(ws_p, {"type": "game_aborted", "message": "Game was aborted", "reason": reason})
                # Persist to DB (best-effort)
                try:
                    await db.record_game_end(game, "aborted")
                    await db.delete_active_game(game_id)
                except Exception as exc:
                    log.error("abort_game: DB persist failed for game=%s: %s", game_id, exc)
                await broadcast_lobby_state()

            else:
                await send(ws, {"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        player_id = pid[0]
        connections.pop(player_id, None)
        game_id = player_games.get(player_id)
        log.info(
            "ws disconnect: pid=%s game_id=%s remaining_connections=%d",
            player_id, game_id, len(connections),
        )
        # Keep player in their game so they can reconnect (handles iOS focus loss,
        # brief network drops, etc). Games are only cleaned up when they end.
        await broadcast_lobby_state()
    except Exception as exc:
        player_id = pid[0]
        connections.pop(player_id, None)
        log.exception("ws error: pid=%s: %s", player_id, exc)
        await broadcast_lobby_state()
