"""
cogs/list_unsolved.py — /listunsolved: paginated list of unsolved attempted problems
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed
from utils.paginator import Paginator, build_unsolved_pages
from cogs.gimme import tag_autocomplete, rating_autocomplete

log = logging.getLogger(__name__)

class ListUnsolved(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="listunsolved",
        description="List your attempted-but-unsolved Codeforces problems (newest first).",
    )
    @app_commands.describe(
        handle="Override: look up a specific CF handle instead of your linked one",
        rating="Filter by exact problem rating (optional)",
        tag="Filter by problem tag (optional)",
    )
    @app_commands.autocomplete(tag=tag_autocomplete, rating=rating_autocomplete)
    async def listunsolved(
        self,
        interaction: discord.Interaction,
        handle: Optional[str] = None,
        rating: Optional[int] = None,
        tag: Optional[str] = None,
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        # Resolve handle
        if handle is None:
            handle = await q.get_handle(db, interaction.user.id)
            if not handle:
                await interaction.followup.send(
                    embed=error_embed("You haven't linked a handle. Use **/setup** first, or pass a `handle` argument."),
                    ephemeral=True,
                )
                return

        try:
            unsolved = await cf.get_unsolved_attempted(handle)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        if not unsolved:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ All Clear!",
                    description=f"**{handle}** has no pending unsolved attempts — great job!",
                    color=0x57F287,
                )
            )
            return

        # Optional filters
        if rating is not None:
            unsolved = [s for s in unsolved if s.problem.rating == rating]
        if tag:
            tag_lower = tag.lower().strip()
            unsolved = [s for s in unsolved if tag_lower in [t.lower() for t in s.problem.tags]]

        if not unsolved:
            await interaction.followup.send(
                embed=error_embed("No unsolved problems match the given filters."),
            )
            return

        pages = build_unsolved_pages(unsolved, per_page=10)

        # Add summary info to first page
        pages[0].description = (
            f"**{handle}** has **{len(unsolved)}** unsolved attempted problems.\n"
            + (pages[0].description or "")
        )

        view = Paginator(pages, author_id=interaction.user.id)
        msg = await interaction.followup.send(embed=pages[0], view=view)
        view.message = msg

async def setup(bot: commands.Bot):
    await bot.add_cog(ListUnsolved(bot))
