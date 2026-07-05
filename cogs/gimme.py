"""
cogs/gimme.py — /gimme: problem recommender (random or latest unsolved)
"""
from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed, problem_embed

log = logging.getLogger(__name__)

CF_TAGS = [
    "2-sat", "binary search", "bitmasks", "brute force", "chinese remainder theorem",
    "combinatorics", "constructive algorithms", "data structures", "dfs and similar",
    "divide and conquer", "dp", "dsu", "expression parsing", "fft", "flows",
    "games", "geometry", "graph matchings", "graphs", "greedy", "hashing",
    "implementation", "interactive", "math", "matrices", "meet-in-the-middle",
    "number theory", "probabilities", "schedules", "shortest paths", "sortings",
    "string suffix structures", "strings", "ternary search", "trees", "two pointers",
]

CF_RATINGS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700,
              1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800, 3000, 3200, 3500]

async def tag_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    lower = current.lower()
    matches = [t for t in CF_TAGS if lower in t][:25]
    return [app_commands.Choice(name=t, value=t) for t in matches]

async def rating_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    try:
        val = int(current)
        matches = [r for r in CF_RATINGS if str(r).startswith(str(val))]
    except ValueError:
        matches = CF_RATINGS
    return [app_commands.Choice(name=str(r), value=r) for r in matches[:25]]

class Gimme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="gimme",
        description="Get a Codeforces problem recommendation.",
    )
    @app_commands.describe(
        mode="random: any problem | latest_unsolved: newest unAC'd problem",
        rating="Problem difficulty rating (e.g. 1600)",
        tags="Comma-separated tags (e.g. dp,graphs)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="🎲 Random unsolved", value="random"),
        app_commands.Choice(name="🕐 Latest unsolved (newest first)", value="latest_unsolved"),
    ])
    @app_commands.autocomplete(tags=tag_autocomplete, rating=rating_autocomplete)
    async def gimme(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        rating: int,
        tags: str = "",
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        handle = await q.get_handle(db, interaction.user.id)
        if not handle:
            await interaction.followup.send(
                embed=error_embed("You haven't linked a Codeforces handle yet.\nUse **/setup** first."),
                ephemeral=True,
            )
            return

        if rating not in CF_RATINGS:
            closest = min(CF_RATINGS, key=lambda r: abs(r - rating))
            await interaction.followup.send(
                embed=error_embed(
                    f"**{rating}** is not a standard CF rating.\n"
                    f"Closest valid rating: **{closest}**. Try that instead."
                ),
                ephemeral=True,
            )
            return

        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []

        try:
            solved = await cf.get_solved_problems(handle)
            all_problems = await cf.get_problemset(tag_list if tag_list else None)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        candidates = [p for p in all_problems if p.rating == rating and p.display_id not in solved]

        if tag_list:
            tag_set = set(tag_list)
            candidates = [p for p in candidates if tag_set.issubset(set(p.tags))]

        if not candidates:
            await interaction.followup.send(
                embed=error_embed(
                    f"No unsolved problems found at rating **{rating}**"
                    + (f" with tags **{', '.join(tag_list)}**" if tag_list else "")
                    + ".\nTry different filters!"
                ),
            )
            return

        mode_val = mode.value if isinstance(mode, app_commands.Choice) else mode

        if mode_val == "random":
            
            candidates.sort(key=lambda p: (p.contest_id, -ord(p.index[0]) if p.index else 0), reverse=True)
            problem = random.choice(candidates[:50])
            title = "🎲 Random Recommendation"
        else:
            
            candidates.sort(key=lambda p: (p.contest_id, -ord(p.index[0]) if p.index else 0), reverse=True)
            problem = candidates[0]
            title = "🕐 Latest Unsolved Problem"

        embed = problem_embed(problem, title=title)
        embed.set_footer(text=f"Handle: {handle}  •  Solved {len(solved)} problems total")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Gimme(bot))
