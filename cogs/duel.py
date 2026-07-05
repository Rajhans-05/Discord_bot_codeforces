"""
cogs/duel.py — /duel: 1v1 problem race with polling for AC submissions
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import duel_embed, error_embed, info_embed

log = logging.getLogger(__name__)

CF_RATINGS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700,
              1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800]

class AcceptView(discord.ui.View):
    """Accept / Decline buttons sent to the opponent."""

    def __init__(self, challenger: discord.Member, opponent: discord.Member, timeout: float):
        super().__init__(timeout=timeout)
        self.challenger = challenger
        self.opponent = opponent
        self.accepted: Optional[bool] = None

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge isn't for you!", ephemeral=True)
            return
        self.accepted = True
        for item in self.children:
            item.disabled = True  
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id not in (self.opponent.id, self.challenger.id):
            await interaction.response.send_message("You can't decline this!", ephemeral=True)
            return
        self.accepted = False
        for item in self.children:
            item.disabled = True  
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        self.accepted = False
        for item in self.children:
            item.disabled = True  
        self.stop()

class Duel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_polls: dict[int, asyncio.Task] = {}  # challenge_id → poll task

    duel_group = app_commands.Group(name="duel", description="1v1 problem race commands")

    # ── /duel challenge ────────────────────────────────────────────────────

    @duel_group.command(name="challenge", description="Challenge someone to a 1v1 CF problem race!")
    @app_commands.describe(
        opponent="The Discord member you want to duel",
        rating="Problem rating for the duel",
        tags="Comma-separated problem tags (optional)",
    )
    async def challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        rating: int,
        tags: str = "",
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        if opponent.bot or opponent.id == interaction.user.id:
            await interaction.followup.send(
                embed=error_embed("You can't duel a bot or yourself!"), ephemeral=True
            )
            return

        # Both users must be registered
        challenger_handle = await q.get_handle(db, interaction.user.id)
        opponent_handle = await q.get_handle(db, opponent.id)

        if not challenger_handle:
            await interaction.followup.send(
                embed=error_embed("You need to **/setup** your handle first."), ephemeral=True
            )
            return
        if not opponent_handle:
            await interaction.followup.send(
                embed=error_embed(f"{opponent.mention} hasn't linked a CF handle. Ask them to **/setup** first."),
            )
            return

        # Find a problem neither has solved
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
        try:
            solved_a = await cf.get_solved_problems(challenger_handle)
            solved_b = await cf.get_solved_problems(opponent_handle)
            all_solved = solved_a | solved_b
            problems = await cf.get_problemset(tag_list if tag_list else None)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        candidates = [p for p in problems if p.rating == rating and p.display_id not in all_solved]
        if tag_list:
            tag_set = set(tag_list)
            candidates = [p for p in candidates if tag_set.issubset(set(p.tags))]

        if not candidates:
            await interaction.followup.send(
                embed=error_embed(
                    f"No problem found at rating **{rating}** that neither of you has solved."
                    + (f" (tags: {', '.join(tag_list)})" if tag_list else "")
                ),
            )
            return

        problem = random.choice(candidates)
        deadline_ts = int(time.time()) + 3600 * 2  # 2-hour max window

        embed = duel_embed(interaction.user, opponent, problem, deadline_ts)
        view = AcceptView(interaction.user, opponent, timeout=float(config.DUEL_ACCEPT_TIMEOUT))
        msg = await interaction.followup.send(
            content=f"{opponent.mention}, you've been challenged!",
            embed=embed,
            view=view,
        )

        await view.wait()

        if not view.accepted:
            await msg.edit(
                embed=info_embed(
                    f"The duel was {'declined' if view.accepted is False else 'timed out'}.",
                    title="Duel Cancelled",
                ),
                view=None,
            )
            return

        # Accepted — record in DB and start polling
        start_time = int(time.time())
        challenge_id = await q.create_challenge(
            db,
            challenger_id=interaction.user.id,
            opponent_id=opponent.id,
            problem_id=problem.display_id,
            problem_url=problem.url,
            problem_name=problem.name,
            start_time=start_time,
            deadline=deadline_ts,
        )

        await msg.edit(
            embed=discord.Embed(
                title="⚔️ Duel Started!",
                description=(
                    f"**[{problem.display_id} — {problem.name}]({problem.url})**\n\n"
                    f"First to submit AC wins! Good luck!\n"
                    f"{interaction.user.mention} vs {opponent.mention}"
                ),
                color=config.COLOUR_OK,
            ),
            view=None,
        )

        # Start background polling task
        task = asyncio.create_task(
            self._poll_duel(
                challenge_id=challenge_id,
                channel=interaction.channel,
                challenger=(interaction.user, challenger_handle),
                opponent=(opponent, opponent_handle),
                problem=problem,
                start_time=start_time,
                deadline_ts=deadline_ts,
            )
        )
        self._active_polls[challenge_id] = task

    # ── /duel history ──────────────────────────────────────────────────────

    @duel_group.command(name="history", description="View your duel win/loss record.")
    @app_commands.describe(member="Member to look up (default: yourself)")
    async def history(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        db = self.bot.db  

        stats = await q.get_duel_stats(db, target.id)
        total = stats["wins"] + stats["losses"]
        winrate = f"{100 * stats['wins'] / total:.1f}%" if total else "N/A"

        embed = discord.Embed(
            title=f"⚔️ Duel Stats — {target.display_name}",
            color=config.COLOUR_INFO,
        )
        embed.add_field(name="🏆 Wins", value=str(stats["wins"]), inline=True)
        embed.add_field(name="💀 Losses", value=str(stats["losses"]), inline=True)
        embed.add_field(name="📊 Win Rate", value=winrate, inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ── /duel leaderboard ─────────────────────────────────────────────────

    @duel_group.command(name="leaderboard", description="Top duel winners in this server.")
    async def leaderboard(self, interaction: discord.Interaction):
        db = self.bot.db  
        rows = await q.get_duel_leaderboard(db, limit=10)

        embed = discord.Embed(title="🏆 Duel Leaderboard", color=config.COLOUR_WARN)
        if not rows:
            embed.description = "No duels recorded yet. Start one with **/duel challenge**!"
        else:
            medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 10
            lines = []
            for i, row in enumerate(rows):
                try:
                    member = interaction.guild.get_member(row["discord_id"])  
                    name = member.display_name if member else f"User #{row['discord_id']}"
                except Exception:
                    name = f"User #{row['discord_id']}"
                lines.append(f"{medals[i]} **{name}** — {row['wins']} wins")
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed)

    # ── Background polling ─────────────────────────────────────────────────

    async def _poll_duel(
        self,
        challenge_id: int,
        channel,
        challenger: tuple,
        opponent: tuple,
        problem,
        start_time: int,
        deadline_ts: int,
    ):
        cf = self.bot.cf   
        db = self.bot.db   
        challenger_member, challenger_handle = challenger
        opponent_member, opponent_handle = opponent

        try:
            while int(time.time()) < deadline_ts:
                await asyncio.sleep(config.DUEL_POLL_INTERVAL)

                # Check if challenge still active
                row = await q.get_active_challenge(db, challenge_id)
                if not row:
                    return  # already resolved

                try:
                    subs_a = await cf.get_user_submissions(challenger_handle, count=50)
                    subs_b = await cf.get_user_submissions(opponent_handle, count=50)
                except CFAPIError:
                    continue

                pid = problem.display_id
                winner = None
                winner_member = None
                loser_member = None

                # Find who submitted AC after start_time
                ac_a = next(
                    (s for s in subs_a if s.problem.display_id == pid
                     and s.is_accepted and s.time_seconds >= start_time),
                    None,
                )
                ac_b = next(
                    (s for s in subs_b if s.problem.display_id == pid
                     and s.is_accepted and s.time_seconds >= start_time),
                    None,
                )

                if ac_a and ac_b:
                    # Both solved — earlier wins
                    if ac_a.time_seconds <= ac_b.time_seconds:
                        winner, winner_member, loser_member = challenger_handle, challenger_member, opponent_member
                        win_time = ac_a.time_seconds - start_time
                    else:
                        winner, winner_member, loser_member = opponent_handle, opponent_member, challenger_member
                        win_time = ac_b.time_seconds - start_time
                elif ac_a:
                    winner, winner_member, loser_member = challenger_handle, challenger_member, opponent_member
                    win_time = ac_a.time_seconds - start_time
                elif ac_b:
                    winner, winner_member, loser_member = opponent_handle, opponent_member, challenger_member
                    win_time = ac_b.time_seconds - start_time

                if winner:
                    await q.resolve_challenge(db, challenge_id)
                    await q.record_duel(
                        db,
                        winner_id=winner_member.id,
                        loser_id=loser_member.id,
                        problem_url=problem.url,
                        problem_name=problem.name,
                        rating=problem.rating,
                        duration_sec=win_time,
                    )
                    mins, secs = divmod(win_time, 60)
                    embed = discord.Embed(
                        title="🏆 Duel Result!",
                        description=(
                            f"{winner_member.mention} won the duel against {loser_member.mention}!\n\n"
                            f"**Problem:** [{problem.display_id} — {problem.name}]({problem.url})\n"
                            f"**Time:** {mins}m {secs}s"
                        ),
                        color=config.COLOUR_OK,
                    )
                    await channel.send(embed=embed)
                    return

            # Deadline reached — no winner
            await q.resolve_challenge(db, challenge_id, status="expired")
            embed = discord.Embed(
                title="⏰ Duel Expired",
                description=(
                    f"Neither {challenger_member.mention} nor {opponent_member.mention} "
                    f"solved **[{problem.display_id} — {problem.name}]({problem.url})** in time."
                ),
                color=config.COLOUR_ERROR,
            )
            await channel.send(embed=embed)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.exception("Error in duel poll for challenge %d: %s", challenge_id, exc)
        finally:
            self._active_polls.pop(challenge_id, None)

async def setup(bot: commands.Bot):
    await bot.add_cog(Duel(bot))
