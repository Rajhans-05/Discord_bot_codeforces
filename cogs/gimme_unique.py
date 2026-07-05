"""
cogs/gimme_unique.py — /gimme_unique: novel/unique question recommender
"""
from __future__ import annotations

import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed, problem_embed
from cogs.gimme import rating_autocomplete

log = logging.getLogger(__name__)

class GimmeUnique(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="gimme_unique",
        description="Get a unique/novel Codeforces problem recommendation (e.g., April Fools).",
    )
    @app_commands.describe(
        rating="Problem difficulty rating (e.g. 1600)",
    )
    @app_commands.autocomplete(rating=rating_autocomplete)
    async def gimme_unique(
        self,
        interaction: discord.Interaction,
        rating: int,
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

        try:
            solved = await cf.get_solved_problems(handle)
            all_problems = await cf.get_problemset()
            all_contests = await cf.get_contests()
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        contest_map = {c.contest_id: c.name for c in all_contests}

        candidates = [p for p in all_problems if p.rating == rating and p.display_id not in solved]
        if not candidates:
            candidates = [p for p in all_problems if p.rating is not None and abs(p.rating - rating) <= 200 and p.display_id not in solved]

        high_pref_keywords = [
            "global", "good bye", "hello", "codeton", "pinely", "nebius", 
            "harbour", "vk cup", "yandex", "tinkoff", "playrix", "mail.ru"
        ]
        
        weighted_candidates = []
        weights = []

        for p in candidates:
            c_name = contest_map.get(p.contest_id, "").lower()
            weight = 0

            if any(kw in c_name for kw in high_pref_keywords):
                weight = 3

            if "*special" in p.tags or "april fools" in c_name:
                weight = max(weight, 1)  # If it didn't get high preference, give it 1

            if weight > 0:
                weighted_candidates.append(p)
                weights.append(weight)

        if not weighted_candidates:
            await interaction.followup.send(
                embed=error_embed(
                    f"No unique/novel problems found near rating **{rating}**.\n"
                    "Try a different rating."
                ),
            )
            return

        problem = random.choices(weighted_candidates, weights=weights, k=1)[0]
        title = "✨ Unique Problem Recommendation"

        embed = problem_embed(problem, title=title)
        c_name = contest_map.get(problem.contest_id, "Unknown Contest")
        embed.description = (embed.description or "") + f"\n\n*Note: This is a unique problem from **{c_name}***"
        embed.set_footer(text=f"Handle: {handle}  •  Solved {len(solved)} problems total")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(GimmeUnique(bot))
