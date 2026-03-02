"""
Game persistence layer.

Tables:
  active_games          — full serialized state of in-progress games;
                          reloaded into memory on server startup so
                          a machine restart doesn't lose ongoing games.
  game_history          — one row per completed/aborted game.
  game_history_players  — one row per (game, player) for player-level queries.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiosqlite

from auth import DB_PATH


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

async def init_game_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_games (
                game_id    TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_history (
                game_id       TEXT PRIMARY KEY,
                end_status    TEXT NOT NULL,
                winner_name   TEXT,
                winner_id     TEXT,
                player_count  INTEGER NOT NULL,
                started_at    TEXT,
                ended_at      TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_history_players (
                game_id     TEXT NOT NULL,
                player_id   TEXT NOT NULL,
                player_name TEXT NOT NULL,
                is_bot      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (game_id, player_id)
            )
        """)
        await db.commit()


# ---------------------------------------------------------------------------
# Active game persistence
# ---------------------------------------------------------------------------

async def save_active_game(game) -> None:
    """Upsert the full game state. Called after every state change."""
    state_json = json.dumps(game.to_dict())
    updated_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO active_games (game_id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET state_json=excluded.state_json,
                                               updated_at=excluded.updated_at
            """,
            (game.game_id, state_json, updated_at),
        )
        await db.commit()


async def delete_active_game(game_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM active_games WHERE game_id = ?", (game_id,))
        await db.commit()


async def load_active_games() -> List:
    """Return all active Game objects persisted from a previous run."""
    from game import Game  # avoid circular import at module level
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT state_json FROM active_games ORDER BY updated_at"
        ) as cur:
            rows = await cur.fetchall()
    games = []
    for row in rows:
        try:
            d = json.loads(row["state_json"])
            games.append(Game.from_dict(d))
        except Exception:
            pass  # corrupt row — skip
    return games


# ---------------------------------------------------------------------------
# Game history
# ---------------------------------------------------------------------------

async def record_game_end(game, end_status: str) -> None:
    """
    Write a completed game to the history tables.
    end_status: 'ended' | 'aborted'
    """
    ended_at = game.ended_at or datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO game_history
                (game_id, end_status, winner_name, winner_id,
                 player_count, started_at, ended_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                game.game_id,
                end_status,
                game.winner,
                game.winner_id,
                len(game.players),
                game.started_at,
                ended_at,
            ),
        )
        for p in game.players:
            await db.execute(
                """
                INSERT OR IGNORE INTO game_history_players
                    (game_id, player_id, player_name, is_bot)
                VALUES (?,?,?,?)
                """,
                (game.game_id, p["id"], p["name"], int(p.get("is_bot", False))),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# History queries
# ---------------------------------------------------------------------------

async def get_recent_games(limit: int = 20, offset: int = 0) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT h.game_id, h.end_status, h.winner_name, h.winner_id,
                   h.player_count, h.started_at, h.ended_at
            FROM game_history h
            ORDER BY h.ended_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()

    results = []
    for row in rows:
        results.append(await _enrich_history_row(dict(row)))
    return results


async def get_games_for_player(
    player_id: str, limit: int = 20, offset: int = 0
) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT h.game_id, h.end_status, h.winner_name, h.winner_id,
                   h.player_count, h.started_at, h.ended_at
            FROM game_history h
            JOIN game_history_players p ON p.game_id = h.game_id
            WHERE p.player_id = ?
            ORDER BY h.ended_at DESC
            LIMIT ? OFFSET ?
            """,
            (player_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()

    results = []
    for row in rows:
        results.append(await _enrich_history_row(dict(row)))
    return results


async def get_game_detail(game_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM game_history WHERE game_id = ?", (game_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return await _enrich_history_row(dict(row))


async def _enrich_history_row(row: Dict) -> Dict:
    """Add the players list to a game_history row."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT player_id, player_name, is_bot FROM game_history_players WHERE game_id = ?",
            (row["game_id"],),
        ) as cur:
            players = [dict(r) for r in await cur.fetchall()]
    row["players"] = players
    return row
