"""
cogs/graphs.py — /graph: rating history, tag bar chart, submission heatmap
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed
from utils import graph_gen

log = logging.getLogger(__name__)

class Graphs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    graphs_group = app_commands.Group(name="graph", description="Visualise your Codeforces stats")

    async def _resolve_handle(self, interaction: discord.Interaction, member: Optional[discord.Member]) -> Optional[str]:
        db = self.bot.db  
        target = member or interaction.user
        handle = await q.get_handle(db, target.id)
        if not handle:
            name = target.display_name if member else "You"
            await interaction.followup.send(
                embed=error_embed(
                    f"{'**' + name + '**' if member else 'You'} haven't linked a CF handle. "
                    "Use **/setup** first."
                ),
                ephemeral=True,
            )
        return handle

    # ── /graph rating ──────────────────────────────────────────────────────

    @graphs_group.command(name="rating", description="Plot rating history over time.")
    @app_commands.describe(member="Member to look up (default: yourself)")
    async def rating(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer()
        handle = await self._resolve_handle(interaction, member)
        if not handle:
            return

        cf = self.bot.cf  
        try:
            rating_changes = await cf._request("user.rating", {"handle": handle})
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        if not rating_changes:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"**{handle}** has no rated contest history yet.",
                    color=0x808080,
                )
            )
            return

        try:
            buf = graph_gen.generate_rating_graph(rating_changes, handle)
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Failed to generate graph: {e}"))
            return

        file = discord.File(buf, filename="rating.png")
        embed = discord.Embed(title=f"📈 Rating History — {handle}", color=0x5865F2)
        embed.set_image(url="attachment://rating.png")
        await interaction.followup.send(embed=embed, file=file)

    # ── /graph tags ────────────────────────────────────────────────────────

    @graphs_group.command(name="tags", description="Bar chart of problems solved by tag.")
    @app_commands.describe(member="Member to look up (default: yourself)")
    async def tags(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer()
        handle = await self._resolve_handle(interaction, member)
        if not handle:
            return

        cf = self.bot.cf  
        try:
            subs = await cf.get_user_submissions(handle)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        try:
            buf = graph_gen.generate_tag_bar(subs, handle)
        except ValueError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Graph error: {e}"))
            return

        file = discord.File(buf, filename="tags.png")
        embed = discord.Embed(title=f"🏷️ Tags Distribution — {handle}", color=0x5865F2)
        embed.set_image(url="attachment://tags.png")
        await interaction.followup.send(embed=embed, file=file)

    # ── /graph heatmap ─────────────────────────────────────────────────────

    @graphs_group.command(name="heatmap", description="GitHub-style submission activity heatmap.")
    @app_commands.describe(member="Member to look up (default: yourself)")
    async def heatmap(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer()
        handle = await self._resolve_handle(interaction, member)
        if not handle:
            return

        cf = self.bot.cf  
        try:
            subs = await cf.get_user_submissions(handle)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        try:
            buf = graph_gen.generate_heatmap(subs, handle)
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Graph error: {e}"))
            return

        file = discord.File(buf, filename="heatmap.png")
        embed = discord.Embed(title=f"📅 Submission Heatmap — {handle}", color=0x5865F2)
        embed.set_image(url="attachment://heatmap.png")
        await interaction.followup.send(embed=embed, file=file)

async def setup(bot: commands.Bot):
    await bot.add_cog(Graphs(bot))
