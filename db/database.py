"""
db/database.py — Async SQLite database setup using aiosqlite
"""
from __future__ import annotations

import logging
import os

import aiosqlite

log = logging.getLogger(__name__)

async def get_db(db_path: str) -> aiosqlite.Connection:
    """Open a connection and enable WAL + foreign keys."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db

async def init_db(db: aiosqlite.Connection) -> None:
    """Create all tables if they do not already exist."""
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id      INTEGER PRIMARY KEY,
            cf_handle       TEXT    NOT NULL UNIQUE,
            registered_at   INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS active_challenges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id   INTEGER NOT NULL,
            opponent_id     INTEGER NOT NULL,
            problem_id      TEXT    NOT NULL,   -- e.g. "1234A"
            problem_url     TEXT    NOT NULL,
            problem_name    TEXT    NOT NULL,
            start_time      INTEGER NOT NULL,
            deadline        INTEGER NOT NULL,   -- Unix timestamp
            status          TEXT    NOT NULL DEFAULT 'pending',
            FOREIGN KEY (challenger_id) REFERENCES users(discord_id),
            FOREIGN KEY (opponent_id)   REFERENCES users(discord_id)
        );

        CREATE TABLE IF NOT EXISTS duel_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            winner_id       INTEGER NOT NULL,
            loser_id        INTEGER NOT NULL,
            problem_url     TEXT    NOT NULL,
            problem_name    TEXT    NOT NULL,
            rating          INTEGER,
            duration_sec    INTEGER,
            timestamp       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (winner_id) REFERENCES users(discord_id),
            FOREIGN KEY (loser_id)  REFERENCES users(discord_id)
        );

        CREATE TABLE IF NOT EXISTS gitgud_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id      INTEGER NOT NULL,
            problem_url     TEXT    NOT NULL,
            problem_name    TEXT    NOT NULL,
            rating          INTEGER,
            tags            TEXT,               -- JSON array
            time_limit_min  INTEGER,
            solved          INTEGER NOT NULL DEFAULT 0,  -- 0 or 1
            timestamp       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (discord_id) REFERENCES users(discord_id)
        );

        CREATE TABLE IF NOT EXISTS virtual_contest_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id          INTEGER NOT NULL,
            contest_id          INTEGER NOT NULL,
            contest_name        TEXT    NOT NULL,
            division            TEXT,
            total_score         INTEGER NOT NULL DEFAULT 0,
            estimated_rank      INTEGER,
            total_participants  INTEGER,
            total_solved        INTEGER NOT NULL DEFAULT 0,
            total_problems      INTEGER NOT NULL DEFAULT 0,
            duration_sec        INTEGER,
            problem_results     TEXT,       -- JSON array of per-problem results
            timestamp           INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (discord_id) REFERENCES users(discord_id)
        );
    """)
    await db.commit()
    log.info("Database tables initialised")
