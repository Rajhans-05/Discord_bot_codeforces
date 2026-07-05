"""
utils/embed_builder.py — Consistent Discord embed builders
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord

import config
from cf_api.models import CFUser, Contest, Problem

def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def error_embed(message: str, title: str = "Error") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=message, color=config.COLOUR_ERROR)

def success_embed(message: str, title: str = "Success") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=message, color=config.COLOUR_OK)

def info_embed(message: str, title: str = "Info") -> discord.Embed:
    return discord.Embed(title=f"ℹ️ {title}", description=message, color=config.COLOUR_INFO)

def problem_embed(problem: Problem, title: str = "Problem Recommendation") -> discord.Embed:
    rating_str = str(problem.rating) if problem.rating else "Unrated"
    tags_str = ", ".join(problem.tags) if problem.tags else "None"

    embed = discord.Embed(
        title=f"📝 {problem.display_id} — {problem.name}",
        url=problem.url,
        color=_rating_colour(problem.rating),
    )
    embed.set_author(name=title)
    embed.add_field(name="⭐ Rating", value=rating_str, inline=True)
    embed.add_field(name="🏷️ Tags", value=tags_str, inline=True)
    embed.set_footer(text=_now_ts())
    return embed

def profile_embed(user: CFUser, solved_count: int = 0, discord_user: Optional[discord.User] = None) -> discord.Embed:
    rank = user.rank or "Unrated"
    rating = str(user.rating) if user.rating else "—"
    max_rating = str(user.max_rating) if user.max_rating else "—"

    embed = discord.Embed(
        title=f"👤 {user.handle}",
        url=f"https://codeforces.com/profile/{user.handle}",
        color=_rating_colour(user.rating),
    )
    if discord_user:
        embed.set_thumbnail(url=discord_user.display_avatar.url)

    embed.add_field(name="🏅 Rank", value=rank.title(), inline=True)
    embed.add_field(name="⭐ Rating", value=rating, inline=True)
    embed.add_field(name="🔝 Max Rating", value=max_rating, inline=True)
    embed.add_field(name="✅ Problems Solved", value=str(solved_count), inline=True)
    embed.add_field(name="❤️ Max Rank", value=(user.max_rank or "—").title(), inline=True)
    embed.add_field(name="🤝 Friend of", value=str(user.friend_of_count), inline=True)
    embed.set_footer(text=_now_ts())
    return embed

def contest_embed(contest: Contest) -> discord.Embed:
    start = datetime.fromtimestamp(contest.start_time_seconds, tz=timezone.utc)
    duration_h = contest.duration_seconds // 3600
    duration_m = (contest.duration_seconds % 3600) // 60

    embed = discord.Embed(
        title=f"🏆 {contest.name}",
        url=contest.url,
        color=config.COLOUR_INFO,
    )
    embed.add_field(name="📅 Start Time", value=discord.utils.format_dt(start, style="F"), inline=False)
    embed.add_field(name="⏳ Time Until Start", value=discord.utils.format_dt(start, style="R"), inline=True)
    embed.add_field(name="⏱️ Duration", value=f"{duration_h}h {duration_m}m", inline=True)
    return embed

def duel_embed(
    challenger: discord.Member,
    opponent: discord.Member,
    problem: Problem,
    deadline_ts: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ Duel Challenge",
        description=f"{challenger.mention} has challenged {opponent.mention}!",
        color=config.COLOUR_WARN,
    )
    embed.add_field(name="📝 Problem", value=f"[{problem.display_id} — {problem.name}]({problem.url})", inline=False)
    embed.add_field(name="⭐ Rating", value=str(problem.rating or "?"), inline=True)
    embed.add_field(name="🏷️ Tags", value=", ".join(problem.tags) or "None", inline=True)
    deadline_dt = datetime.fromtimestamp(deadline_ts, tz=timezone.utc)
    embed.add_field(name="⏰ Deadline", value=discord.utils.format_dt(deadline_dt, style="R"), inline=False)
    embed.set_footer(text="First to submit AC wins!")
    return embed

def _rating_colour(rating: Optional[int]) -> int:
    """Map CF rating to a colour used on their site."""
    if not rating:
        return 0x808080  # grey — unrated
    if rating < 1200:
        return 0x808080  # grey
    if rating < 1400:
        return 0x008000  # green
    if rating < 1600:
        return 0x03A89E  # cyan
    if rating < 1900:
        return 0x0000FF  # blue
    if rating < 2100:
        return 0xAA00AA  # violet
    if rating < 2400:
        return 0xFF8C00  # orange
    return 0xFF0000      # red — 2400+
