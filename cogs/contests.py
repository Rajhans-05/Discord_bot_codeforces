"""
cogs/contests.py — /contests: upcoming CF contests with countdowns and reminders
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from cf_api.client import CFAPIError
from utils.embed_builder import contest_embed, error_embed

log = logging.getLogger(__name__)

class Contests(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # discord_id → list of (contest_id, start_time_seconds)
        self._reminders: dict[int, list[tuple[int, int]]] = {}

    contests_group = app_commands.Group(name="contests", description="Codeforces contest commands")

    # ── /contests upcoming ─────────────────────────────────────────────────

    @contests_group.command(name="upcoming", description="Show upcoming Codeforces contests.")
    @app_commands.describe(count="Number of contests to show (1–10, default: 5)")
    async def upcoming(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 10] = 5,
    ):
        await interaction.response.defer()
        cf = self.bot.cf  

        try:
            contests = await cf.get_upcoming_contests()
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        if not contests:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📅 No Upcoming Contests",
                    description="No Codeforces contests are scheduled right now. Check back later!",
                    color=config.COLOUR_WARN,
                )
            )
            return

        contests = contests[:count]
        embeds = [contest_embed(c) for c in contests]

        # Send as a list embed
        summary = discord.Embed(
            title=f"🏆 Next {len(contests)} Codeforces Contest(s)",
            color=config.COLOUR_INFO,
        )
        for c in contests:
            start_dt = datetime.fromtimestamp(c.start_time_seconds, tz=timezone.utc)
            duration_h = c.duration_seconds // 3600
            duration_m = (c.duration_seconds % 3600) // 60
            summary.add_field(
                name=c.name,
                value=(
                    f"📅 {discord.utils.format_dt(start_dt, style='F')}\n"
                    f"⏳ {discord.utils.format_dt(start_dt, style='R')}\n"
                    f"⏱️ Duration: {duration_h}h {duration_m}m\n"
                    f"🔗 [Register]({c.url})"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=summary)

    # ── /contests remind ───────────────────────────────────────────────────

    @contests_group.command(
        name="remind",
        description="Get a DM reminder when a contest starts (shown in /contests upcoming).",
    )
    @app_commands.describe(contest_id="The Codeforces contest ID (visible in the contest URL)")
    async def remind(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer(ephemeral=True)
        cf = self.bot.cf  

        try:
            all_contests = await cf.get_upcoming_contests()
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        contest = next((c for c in all_contests if c.contest_id == contest_id), None)
        if not contest:
            await interaction.followup.send(
                embed=error_embed(f"Contest ID **{contest_id}** not found in upcoming contests."),
                ephemeral=True,
            )
            return

        uid = interaction.user.id
        if uid not in self._reminders:
            self._reminders[uid] = []

        if any(cid == contest_id for cid, _ in self._reminders[uid]):
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"You're already registered for a reminder for **{contest.name}**.",
                    color=config.COLOUR_WARN,
                ),
                ephemeral=True,
            )
            return

        self._reminders[uid].append((contest_id, contest.start_time_seconds))

        start_dt = datetime.fromtimestamp(contest.start_time_seconds, tz=timezone.utc)
        await interaction.followup.send(
            embed=discord.Embed(
                title="⏰ Reminder Set!",
                description=(
                    f"I'll DM you when **{contest.name}** starts!\n"
                    f"📅 {discord.utils.format_dt(start_dt, style='F')}"
                ),
                color=config.COLOUR_OK,
            ),
            ephemeral=True,
        )

        # Schedule the DM
        asyncio.create_task(self._send_reminder(uid, contest))

    async def _send_reminder(self, discord_id: int, contest) -> None:
        delay = contest.start_time_seconds - int(time.time()) - 300  # 5 min before
        if delay > 0:
            await asyncio.sleep(delay)

        try:
            user = await self.bot.fetch_user(discord_id)
            start_dt = datetime.fromtimestamp(contest.start_time_seconds, tz=timezone.utc)
            await user.send(
                embed=discord.Embed(
                    title="🏆 Contest Starting Soon!",
                    description=(
                        f"**{contest.name}** starts {discord.utils.format_dt(start_dt, style='R')}!\n"
                        f"🔗 [Join the contest]({contest.url})"
                    ),
                    color=config.COLOUR_WARN,
                )
            )
        except discord.HTTPException:
            pass
        finally:
            if discord_id in self._reminders:
                self._reminders[discord_id] = [
                    (cid, ts) for cid, ts in self._reminders[discord_id]
                    if cid != contest.contest_id
                ]

async def setup(bot: commands.Bot):
    await bot.add_cog(Contests(bot))
