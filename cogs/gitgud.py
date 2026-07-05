"""
cogs/gitgud.py — /gitgud: timed solo coding challenge with a thread
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed

log = logging.getLogger(__name__)

CF_TAGS = [
    "2-sat", "binary search", "bitmasks", "brute force", "combinatorics",
    "constructive algorithms", "data structures", "dfs and similar", "divide and conquer",
    "dp", "dsu", "fft", "flows", "games", "geometry", "graphs", "greedy",
    "hashing", "implementation", "math", "number theory", "shortest paths",
    "sortings", "strings", "trees", "two pointers",
]

async def tag_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    lower = current.lower()
    return [app_commands.Choice(name=t, value=t) for t in CF_TAGS if lower in t][:25]

class ResultView(discord.ui.View):
    """Solved / Failed buttons shown after timer expires."""

    def __init__(self, bot, challenge_meta: dict):
        super().__init__(timeout=300)
        self.bot = bot
        self.meta = challenge_meta
        self.done = False

    @discord.ui.button(label="✅ I solved it!", style=discord.ButtonStyle.success)
    async def solved(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.meta["discord_id"]:
            await interaction.response.send_message("This isn't your challenge!", ephemeral=True)
            return
        self.done = True
        await self._record(interaction, solved=True)

    @discord.ui.button(label="❌ I didn't solve it", style=discord.ButtonStyle.danger)
    async def failed(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.meta["discord_id"]:
            await interaction.response.send_message("This isn't your challenge!", ephemeral=True)
            return
        self.done = True
        await self._record(interaction, solved=False)

    async def _record(self, interaction: discord.Interaction, solved: bool):
        for item in self.children:
            item.disabled = True  
        db = self.bot.db  
        await q.record_gitgud(
            db,
            discord_id=self.meta["discord_id"],
            problem_url=self.meta["problem_url"],
            problem_name=self.meta["problem_name"],
            rating=self.meta.get("rating"),
            tags=json.dumps(self.meta.get("tags", [])),
            time_limit_min=self.meta["time_limit_min"],
            solved=solved,
        )
        verb = "solved 🎉" if solved else "didn't solve 😔"
        colour = 0x57F287 if solved else 0xED4245
        embed = discord.Embed(
            title=f"{'🏆' if solved else '💀'} Challenge {'Complete' if solved else 'Failed'}!",
            description=f"You **{verb}** **[{self.meta['problem_name']}]({self.meta['problem_url']})** in time!",
            color=colour,
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

class Gitgud(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="gitgud",
        description="Start a timed solo coding challenge.",
    )
    @app_commands.describe(
        topic="Problem topic/tag (e.g. dp, graphs, greedy)",
        time_limit="Time limit in minutes (e.g. 30)",
        rating="Problem rating (leave blank to auto-pick slightly above your current rating)",
    )
    @app_commands.autocomplete(topic=tag_autocomplete)
    async def gitgud(
        self,
        interaction: discord.Interaction,
        topic: str,
        time_limit: app_commands.Range[int, 5, 300],
        rating: int | None = None,
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        handle = await q.get_handle(db, interaction.user.id)
        if not handle:
            await interaction.followup.send(
                embed=error_embed("Use **/setup** first to link your Codeforces handle."),
                ephemeral=True,
            )
            return

        # Determine target rating
        if rating is None:
            try:
                users = await cf.get_user_info([handle])
                user_rating = users[0].rating or 1200
            except CFAPIError:
                user_rating = 1200
            rating = user_rating + config.GITGUD_DEFAULT_DELTA
            # Round to nearest 100
            rating = round(rating / 100) * 100

        # Fetch problems
        try:
            solved = await cf.get_solved_problems(handle)
            problems = await cf.get_problemset([topic.lower()])
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        candidates = [p for p in problems if p.rating == rating and p.display_id not in solved]
        if not candidates:
            # Relax to ±200 range
            candidates = [
                p for p in problems
                if p.rating and abs(p.rating - rating) <= 200 and p.display_id not in solved
            ]

        if not candidates:
            await interaction.followup.send(
                embed=error_embed(
                    f"No unsolved **{topic}** problems found around rating **{rating}**.\n"
                    "Try a different topic or rating."
                ),
            )
            return

        problem = random.choice(candidates)

        # ── Create a thread for the challenge ────────────────────────────
        channel = interaction.channel
        thread_name = f"🔥 gitgud — {problem.name[:50]}"

        try:
            # Works for text channels
            thread = await channel.create_thread(  
                name=thread_name,
                auto_archive_duration=max(60, time_limit + 10),
                reason="gitgud challenge",
            )
        except (discord.Forbidden, AttributeError):
            # Fallback: no thread (e.g. DMs or forum channels)
            thread = None

        deadline = int(time.time()) + time_limit * 60
        deadline_dt = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=time_limit)

        embed = discord.Embed(
            title=f"🔥 gitgud Challenge — {problem.display_id}",
            description=(
                f"**[{problem.name}]({problem.url})**\n\n"
                f"⭐ **Rating:** {problem.rating}\n"
                f"🏷️ **Tags:** {', '.join(problem.tags)}\n\n"
                f"⏰ **Time Limit:** {time_limit} minutes\n"
                f"🕐 **Deadline:** {discord.utils.format_dt(deadline_dt, style='R')}\n\n"
                f"Good luck, {interaction.user.mention}! 💪"
            ),
            color=config.COLOUR_WARN,
        )

        target = thread or interaction.channel
        msg = await target.send(embed=embed)  

        if thread:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"Challenge started in {thread.mention}! Go! ⚡",
                    color=config.COLOUR_OK,
                )
            )

        # ── Wait for time limit, then post result buttons ─────────────
        async def send_result_after_delay():
            await asyncio.sleep(time_limit * 60)
            meta = {
                "discord_id": interaction.user.id,
                "problem_url": problem.url,
                "problem_name": f"{problem.display_id} — {problem.name}",
                "rating": problem.rating,
                "tags": problem.tags,
                "time_limit_min": time_limit,
            }
            view = ResultView(self.bot, meta)
            result_embed = discord.Embed(
                title="⏰ Time's Up!",
                description=(
                    f"Did you solve **[{problem.display_id} — {problem.name}]({problem.url})**?"
                ),
                color=config.COLOUR_WARN,
            )
            await target.send(  
                content=interaction.user.mention,
                embed=result_embed,
                view=view,
            )

        asyncio.create_task(send_result_after_delay())

async def setup(bot: commands.Bot):
    await bot.add_cog(Gitgud(bot))
