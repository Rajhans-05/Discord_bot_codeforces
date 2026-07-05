"""
utils/paginator.py — Generic button-based embed paginator for discord.py 2.x
"""
from __future__ import annotations

import discord

class Paginator(discord.ui.View):
    """
    Sends a list of embeds with ◀  ▶  navigation buttons.

    Usage:
        view = Paginator(embeds, author_id=interaction.user.id)
        await interaction.followup.send(embed=embeds[0], view=view)
        view.message = ...   # set so the view can edit on button click
    """

    def __init__(self, embeds: list[discord.Embed], author_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.index = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _update_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.embeds) - 1

    def _current_embed(self) -> discord.Embed:
        embed = self.embeds[self.index]
        embed.set_footer(text=f"Page {self.index + 1} / {len(self.embeds)}")
        return embed

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This paginator isn't for you!", ephemeral=True)
            return False
        return True

    # ── Buttons ────────────────────────────────────────────────────────────

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    # ── Timeout ────────────────────────────────────────────────────────────

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True  
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

def build_unsolved_pages(submissions, per_page: int = 10) -> list[discord.Embed]:
    """
    Build paginated embeds for /listunsolved.

    Each embed is a table: # | Problem | Rating | Tags | Last Attempted
    """
    import config
    from datetime import datetime, timezone

    pages: list[discord.Embed] = []
    for i in range(0, len(submissions), per_page):
        chunk = submissions[i : i + per_page]
        embed = discord.Embed(
            title="📋 Unsolved Problems",
            description="Problems you attempted but haven't AC'd yet (newest first).",
            color=config.COLOUR_INFO,
        )
        for j, sub in enumerate(chunk, start=i + 1):
            p = sub.problem
            tags_str = ", ".join(p.tags[:3]) + ("…" if len(p.tags) > 3 else "")
            rating_str = str(p.rating) if p.rating else "?"
            dt = datetime.fromtimestamp(sub.time_seconds, tz=timezone.utc)
            time_str = discord.utils.format_dt(dt, style="R")
            embed.add_field(
                name=f"{j}. [{p.display_id}] {p.name[:40]}",
                value=f"⭐ **{rating_str}**  |  🏷️ {tags_str or 'None'}  |  🕒 {time_str}",
                inline=False,
            )
        pages.append(embed)
    return pages
