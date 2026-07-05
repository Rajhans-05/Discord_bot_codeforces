"""
cogs/profile.py — /profile: full Codeforces user stats
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed, profile_embed

log = logging.getLogger(__name__)

class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="profile",
        description="View Codeforces stats for yourself or another server member.",
    )
    @app_commands.describe(
        member="Discord member to look up (default: yourself)",
        handle="Or type a CF handle directly (overrides member)",
    )
    async def profile(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        handle: Optional[str] = None,
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        discord_user: Optional[discord.User | discord.Member] = None

        if handle:
            # Direct handle lookup — no DB needed
            cf_handle = handle
        elif member:
            cf_handle = await q.get_handle(db, member.id)
            discord_user = member
            if not cf_handle:
                await interaction.followup.send(
                    embed=error_embed(f"{member.mention} hasn't linked a CF handle. Ask them to **/setup**!"),
                )
                return
        else:
            cf_handle = await q.get_handle(db, interaction.user.id)
            discord_user = interaction.user
            if not cf_handle:
                await interaction.followup.send(
                    embed=error_embed("You haven't linked a handle yet. Use **/setup** first."),
                    ephemeral=True,
                )
                return

        # Fetch CF data
        try:
            users = await cf.get_user_info([cf_handle])
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        if not users:
            await interaction.followup.send(
                embed=error_embed(f"Handle **{cf_handle}** not found on Codeforces.")
            )
            return

        cf_user = users[0]

        # Count solved problems
        try:
            solved = await cf.get_solved_problems(cf_handle)
            solved_count = len(solved)
        except CFAPIError:
            solved_count = 0

        embed = profile_embed(cf_user, solved_count=solved_count, discord_user=discord_user)
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
