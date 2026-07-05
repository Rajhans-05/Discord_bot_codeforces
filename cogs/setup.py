"""
cogs/setup.py — /setup command: link Discord user ↔ Codeforces handle
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed, success_embed

log = logging.getLogger(__name__)

class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Link your Codeforces handle to your Discord account.")
    @app_commands.describe(handle="Your Codeforces username (case-sensitive)")
    async def setup(self, interaction: discord.Interaction, handle: str):
        await interaction.response.defer(ephemeral=True)

        cf = self.bot.cf  
        db = self.bot.db  

        # Validate handle exists on CF
        try:
            users = await cf.get_user_info([handle])
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(f"Codeforces API error: {e}"), ephemeral=True)
            return

        if not users:
            await interaction.followup.send(
                embed=error_embed(f"Handle **{handle}** not found on Codeforces."),
                ephemeral=True,
            )
            return

        cf_user = users[0]
        await q.register_user(db, interaction.user.id, cf_user.handle)

        rating_str = f" (Rating: **{cf_user.rating}**)" if cf_user.rating else ""
        embed = success_embed(
            f"Linked to **[{cf_user.handle}](https://codeforces.com/profile/{cf_user.handle})**"
            f"{rating_str}\n\nYou can now use all bot commands!",
            title="Handle Registered",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info("User %s registered as CF handle %s", interaction.user, cf_user.handle)

    @app_commands.command(name="whoami", description="Show your linked Codeforces handle.")
    async def whoami(self, interaction: discord.Interaction):
        db = self.bot.db  
        handle = await q.get_handle(db, interaction.user.id)
        if handle:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"You are linked to **[{handle}](https://codeforces.com/profile/{handle})**",
                    color=0x5865F2,
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=error_embed("You haven't linked a handle yet. Use **/setup** first."),
                ephemeral=True,
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))
