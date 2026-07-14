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

# ── Virtual Contest ────────────────────────────────────────────────────────

async def record_virtual_contest(
    db: aiosqlite.Connection,
    discord_id: int,
    contest_id: int,
    contest_name: str,
    division: str,
    total_score: int,
    estimated_rank: int | None,
    total_participants: int | None,
    total_solved: int,
    total_problems: int,
    duration_sec: int,
    problem_results: str,  # JSON string
) -> None:
    await db.execute(
        """INSERT INTO virtual_contest_history
           (discord_id, contest_id, contest_name, division, total_score,
            estimated_rank, total_participants, total_solved, total_problems,
            duration_sec, problem_results)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (discord_id, contest_id, contest_name, division, total_score,
         estimated_rank, total_participants, total_solved, total_problems,
         duration_sec, problem_results),
    )
    await db.commit()


async def get_user_virtual_history(
    db: aiosqlite.Connection, discord_id: int
) -> list[aiosqlite.Row]:
    """Get all virtual contest attempts for a user (used by contest picker)."""
    async with db.execute(
        """SELECT contest_id, total_solved, total_score, estimated_rank, timestamp
           FROM virtual_contest_history
           WHERE discord_id = ?
           ORDER BY timestamp DESC""",
        (discord_id,),
    ) as cur:
        return await cur.fetchall()


async def get_virtual_contest_stats(
    db: aiosqlite.Connection, discord_id: int
) -> dict:
    """Aggregate virtual contest stats for a user."""
    async with db.execute(
        """SELECT COUNT(*) as total_contests,
                  SUM(total_solved) as total_solved,
                  AVG(total_score) as avg_score
           FROM virtual_contest_history
           WHERE discord_id = ?""",
        (discord_id,),
    ) as cur:
        row = await cur.fetchone()
        return {
            "total_contests": row["total_contests"],
            "total_solved": row["total_solved"] or 0,
            "avg_score": int(row["avg_score"]) if row["avg_score"] else 0,
        }

