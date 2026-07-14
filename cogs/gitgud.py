"""
cogs/gitgud.py — /gitgud: timed solo coding challenge with a thread

After the timer expires, the bot automatically checks the user's CF submissions
to detect whether the problem was solved. Falls back to manual buttons if
auto-detection is inconclusive.
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
    """Solved / Failed buttons — fallback when auto-detection can't confirm."""

    def __init__(self, bot, challenge_meta: dict):
        # Long timeout so buttons stay active for the full challenge window
        super().__init__(timeout=3600)
        self.bot = bot
        self.meta = challenge_meta
        self.done = False

    async def on_timeout(self):
        """Disable buttons when the view times out so they don't show errors."""
        for item in self.children:
            item.disabled = True
        # Try to edit the message to disable buttons visually
        # (we need access to the message, stored by the caller)
        if hasattr(self, "_message") and self._message:
            try:
                await self._message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="✅ I solved it!", style=discord.ButtonStyle.success)
    async def solved(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.meta["discord_id"]:
            await interaction.response.send_message("This isn't your challenge!", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("Already recorded!", ephemeral=True)
            return
        self.done = True
        await self._record(interaction, solved=True)

    @discord.ui.button(label="❌ I didn't solve it", style=discord.ButtonStyle.danger)
    async def failed(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.meta["discord_id"]:
            await interaction.response.send_message("This isn't your challenge!", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("Already recorded!", ephemeral=True)
            return
        self.done = True
        await self._record(interaction, solved=False)

    async def _record(self, interaction: discord.Interaction, solved: bool):
        for item in self.children:
            item.disabled = True
        db = self.bot.db
        try:
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
        except Exception as e:
            log.error("Failed to record gitgud result: %s", e)

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

    async def _check_submission_on_cf(
        self, handle: str, contest_id: int, problem_index: str, after_ts: int
    ) -> tuple[bool, int]:
        """
        Check CF submissions to see if the user solved a problem.

        Returns (solved: bool, wrong_attempts: int).
        """
        cf = self.bot.cf
        try:
            subs = await cf.get_user_submissions(handle)
        except CFAPIError:
            return False, 0

        # Filter to submissions for this specific problem, after the challenge started
        relevant = [
            s for s in subs
            if s.problem.contest_id == contest_id
            and s.problem.index == problem_index
            and s.time_seconds >= after_ts
        ]

        if not relevant:
            return False, 0

        wrong_count = 0
        for sub in sorted(relevant, key=lambda s: s.time_seconds):
            if sub.verdict is None:
                continue
            if sub.is_accepted:
                return True, wrong_count
            else:
                wrong_count += 1

        return False, wrong_count

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

        challenge_start_ts = int(time.time())
        deadline = challenge_start_ts + time_limit * 60
        deadline_dt = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=time_limit)

        embed = discord.Embed(
            title=f"🔥 gitgud Challenge — {problem.display_id}",
            description=(
                f"**[{problem.name}]({problem.url})**\n\n"
                f"⭐ **Rating:** {problem.rating}\n"
                f"🏷️ **Tags:** {', '.join(problem.tags)}\n\n"
                f"⏰ **Time Limit:** {time_limit} minutes\n"
                f"🕐 **Deadline:** {discord.utils.format_dt(deadline_dt, style='R')}\n\n"
                f"Good luck, {interaction.user.mention}! 💪\n"
                f"_Your submissions on CF will be tracked automatically._"
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

        # ── Wait for time limit, auto-check submissions, then post result ──
        user_id = interaction.user.id
        problem_name = f"{problem.display_id} — {problem.name}"
        problem_url = problem.url

        meta = {
            "discord_id": user_id,
            "problem_url": problem_url,
            "problem_name": problem_name,
            "rating": problem.rating,
            "tags": problem.tags,
            "time_limit_min": time_limit,
        }

        async def monitor_and_resolve():
            """
            Monitors submissions during the challenge, auto-detects solve,
            and posts results when the timer expires.
            """
            poll_interval = 30  # check every 30 seconds
            elapsed = 0
            solved_during = False

            # Poll submissions while the timer is running
            while elapsed < time_limit * 60:
                wait_time = min(poll_interval, time_limit * 60 - elapsed)
                await asyncio.sleep(wait_time)
                elapsed += wait_time

                # Check if the user solved it
                try:
                    solved, wrong = await self._check_submission_on_cf(
                        handle, problem.contest_id, problem.index, challenge_start_ts
                    )
                except Exception as e:
                    log.warning("Poll error during gitgud: %s", e)
                    continue

                if solved:
                    solved_during = True
                    solve_time = int(time.time()) - challenge_start_ts
                    solve_min = solve_time // 60

                    # Auto-congratulate!
                    try:
                        await q.record_gitgud(
                            self.bot.db,
                            discord_id=user_id,
                            problem_url=problem_url,
                            problem_name=problem_name,
                            rating=problem.rating,
                            tags=json.dumps(problem.tags),
                            time_limit_min=time_limit,
                            solved=True,
                        )
                    except Exception as e:
                        log.error("Failed to record gitgud: %s", e)

                    congrats_embed = discord.Embed(
                        title="🏆 Challenge Complete!",
                        description=(
                            f"**{interaction.user.mention}** solved "
                            f"**[{problem_name}]({problem_url})** in **{solve_min}m**! 🎉\n\n"
                            f"⏱️ Time: {solve_min} min / {time_limit} min\n"
                            f"❌ Wrong attempts: {wrong}"
                        ),
                        color=0x57F287,
                    )
                    await target.send(
                        content=interaction.user.mention,
                        embed=congrats_embed,
                    )
                    return  # Done! No need for buttons

            # Timer expired — do one final check
            if not solved_during:
                try:
                    solved, wrong = await self._check_submission_on_cf(
                        handle, problem.contest_id, problem.index, challenge_start_ts
                    )
                except Exception:
                    solved = False
                    wrong = 0

                if solved:
                    # They solved it right at the buzzer
                    try:
                        await q.record_gitgud(
                            self.bot.db,
                            discord_id=user_id,
                            problem_url=problem_url,
                            problem_name=problem_name,
                            rating=problem.rating,
                            tags=json.dumps(problem.tags),
                            time_limit_min=time_limit,
                            solved=True,
                        )
                    except Exception as e:
                        log.error("Failed to record gitgud: %s", e)

                    solve_time = int(time.time()) - challenge_start_ts
                    solve_min = solve_time // 60

                    congrats_embed = discord.Embed(
                        title="🏆 Challenge Complete!",
                        description=(
                            f"**{interaction.user.mention}** solved "
                            f"**[{problem_name}]({problem_url})**! 🎉\n\n"
                            f"⏱️ Completed just in time!\n"
                            f"❌ Wrong attempts: {wrong}"
                        ),
                        color=0x57F287,
                    )
                    await target.send(
                        content=interaction.user.mention,
                        embed=congrats_embed,
                    )
                    return

                # Not solved — check if they attempted but failed
                if wrong > 0:
                    # They tried but didn't solve it
                    try:
                        await q.record_gitgud(
                            self.bot.db,
                            discord_id=user_id,
                            problem_url=problem_url,
                            problem_name=problem_name,
                            rating=problem.rating,
                            tags=json.dumps(problem.tags),
                            time_limit_min=time_limit,
                            solved=False,
                        )
                    except Exception as e:
                        log.error("Failed to record gitgud: %s", e)

                    failed_embed = discord.Embed(
                        title="💀 Challenge Failed!",
                        description=(
                            f"**{interaction.user.mention}** attempted but didn't solve "
                            f"**[{problem_name}]({problem_url})** in time. 😔\n\n"
                            f"⏱️ Time limit: {time_limit} min\n"
                            f"❌ Wrong attempts: {wrong}\n\n"
                            f"Don't give up! Try again with `/gitgud` 💪"
                        ),
                        color=0xED4245,
                    )
                    await target.send(
                        content=interaction.user.mention,
                        embed=failed_embed,
                    )
                    return

                # No submissions at all — show fallback buttons
                view = ResultView(self.bot, meta)
                result_embed = discord.Embed(
                    title="⏰ Time's Up!",
                    description=(
                        f"No submissions detected on Codeforces for "
                        f"**[{problem_name}]({problem_url})**.\n\n"
                        f"Did you solve it outside CF, or still working on it?"
                    ),
                    color=config.COLOUR_WARN,
                )
                result_msg = await target.send(
                    content=interaction.user.mention,
                    embed=result_embed,
                    view=view,
                )
                # Store message reference for timeout cleanup
                view._message = result_msg

        asyncio.create_task(monitor_and_resolve())

async def setup(bot: commands.Bot):
    await bot.add_cog(Gitgud(bot))
