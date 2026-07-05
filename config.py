"""
config.py — Load all environment variables from .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Discord ────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
GUILD_ID: int | None = int(os.getenv("GUILD_ID", 0)) or None  # None = global sync (slow)

# ── Codeforces API (optional – public endpoints work without keys) ──────────
CF_API_KEY: str = os.getenv("CF_API_KEY", "")
CF_API_SECRET: str = os.getenv("CF_API_SECRET", "")

# ── Bot behaviour ──────────────────────────────────────────────────────────
PROBLEM_CACHE_TTL: int = int(os.getenv("PROBLEM_CACHE_TTL", 21600))  # seconds (6h)
DUEL_POLL_INTERVAL: int = int(os.getenv("DUEL_POLL_INTERVAL", 60))   # seconds
DUEL_ACCEPT_TIMEOUT: int = int(os.getenv("DUEL_ACCEPT_TIMEOUT", 60)) # seconds
GITGUD_DEFAULT_DELTA: int = int(os.getenv("GITGUD_DEFAULT_DELTA", 200)) # rating above user

# ── Database ───────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")

# ── Embed colours ─────────────────────────────────────────────────────────
COLOUR_OK    = 0x5865F2   # Discord blurple
COLOUR_ERROR = 0xED4245   # red
COLOUR_WARN  = 0xFEE75C   # yellow
COLOUR_INFO  = 0x57F287   # green
