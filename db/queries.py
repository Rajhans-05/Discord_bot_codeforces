"""
db/queries.py — All database queries as typed async functions
"""
from __future__ import annotations

from typing import Optional

import aiosqlite

# ── Users ──────────────────────────────────────────────────────────────────

async def register_user(db: aiosqlite.Connection, discord_id: int, cf_handle: str) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO users (discord_id, cf_handle) VALUES (?, ?)",
        (discord_id, cf_handle),
    )
    await db.commit()

async def get_handle(db: aiosqlite.Connection, discord_id: int) -> Optional[str]:
    async with db.execute(
        "SELECT cf_handle FROM users WHERE discord_id = ?", (discord_id,)
    ) as cur:
        row = await cur.fetchone()
        return row["cf_handle"] if row else None

async def get_all_users(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute("SELECT discord_id, cf_handle FROM users") as cur:
        return await cur.fetchall()

# ── Duel ───────────────────────────────────────────────────────────────────

async def create_challenge(
    db: aiosqlite.Connection,
    challenger_id: int,
    opponent_id: int,
    problem_id: str,
    problem_url: str,
    problem_name: str,
    start_time: int,
    deadline: int,
) -> int:
    cur = await db.execute(
        """INSERT INTO active_challenges
           (challenger_id, opponent_id, problem_id, problem_url, problem_name,
            start_time, deadline, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
        (challenger_id, opponent_id, problem_id, problem_url, problem_name, start_time, deadline),
    )
    await db.commit()
    return cur.lastrowid  

async def get_active_challenge(db: aiosqlite.Connection, challenge_id: int) -> Optional[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM active_challenges WHERE id = ? AND status = 'active'",
        (challenge_id,),
    ) as cur:
        return await cur.fetchone()

async def get_active_challenges_for_user(db: aiosqlite.Connection, discord_id: int) -> list[aiosqlite.Row]:
    async with db.execute(
        """SELECT * FROM active_challenges
           WHERE (challenger_id = ? OR opponent_id = ?) AND status = 'active'""",
        (discord_id, discord_id),
    ) as cur:
        return await cur.fetchall()

async def resolve_challenge(db: aiosqlite.Connection, challenge_id: int, status: str = "done") -> None:
    await db.execute(
        "UPDATE active_challenges SET status = ? WHERE id = ?",
        (status, challenge_id),
    )
    await db.commit()

async def record_duel(
    db: aiosqlite.Connection,
    winner_id: int,
    loser_id: int,
    problem_url: str,
    problem_name: str,
    rating: Optional[int],
    duration_sec: int,
) -> None:
    await db.execute(
        """INSERT INTO duel_history
           (winner_id, loser_id, problem_url, problem_name, rating, duration_sec)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (winner_id, loser_id, problem_url, problem_name, rating, duration_sec),
    )
    await db.commit()

async def get_duel_stats(db: aiosqlite.Connection, discord_id: int) -> dict:
    async with db.execute(
        "SELECT COUNT(*) as wins FROM duel_history WHERE winner_id = ?", (discord_id,)
    ) as cur:
        wins = (await cur.fetchone())["wins"]

    async with db.execute(
        "SELECT COUNT(*) as losses FROM duel_history WHERE loser_id = ?", (discord_id,)
    ) as cur:
        losses = (await cur.fetchone())["losses"]

    return {"wins": wins, "losses": losses}

async def get_duel_leaderboard(db: aiosqlite.Connection, limit: int = 10) -> list[aiosqlite.Row]:
    async with db.execute(
        """SELECT winner_id as discord_id, COUNT(*) as wins
           FROM duel_history
           GROUP BY winner_id
           ORDER BY wins DESC
           LIMIT ?""",
        (limit,),
    ) as cur:
        return await cur.fetchall()

# ── Gitgud ─────────────────────────────────────────────────────────────────

async def record_gitgud(
    db: aiosqlite.Connection,
    discord_id: int,
    problem_url: str,
    problem_name: str,
    rating: Optional[int],
    tags: str,
    time_limit_min: int,
    solved: bool,
) -> None:
    await db.execute(
        """INSERT INTO gitgud_history
           (discord_id, problem_url, problem_name, rating, tags, time_limit_min, solved)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (discord_id, problem_url, problem_name, rating, tags, time_limit_min, int(solved)),
    )
    await db.commit()
