"""
cogs/gitgud_contest.py — /gitgud_contest: virtual Codeforces contest simulation

Full flow:
  1. User picks a division
  2. Bot selects a contest (prioritised: unattempted > few-solved > many-solved)
  3. A thread is created with a live dashboard
  4. A polling loop checks CF submissions every 60s to detect AC/WA
  5. When time expires (or user ends early), scores are computed and rank is estimated
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.queries as q
from cf_api.client import CFAPIError
from cf_api.models import ContestProblem, Contest
from utils.contest_picker import pick_contest
from utils.scoring import calculate_problem_score, estimate_rank, format_rank_percentile
from utils.embed_builder import error_embed

log = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds between submission polls


# ── Per-problem state tracker ─────────────────────────────────────────────

class ProblemTracker:
    """Tracks the state of a single problem during a virtual contest."""

    __slots__ = ("problem", "solved", "solve_time_sec", "wrong_attempts", "score")

    def __init__(self, problem: ContestProblem):
        self.problem = problem
        self.solved: bool = False
        self.solve_time_sec: int | None = None   # seconds from contest start
        self.wrong_attempts: int = 0
        self.score: int = 0

    @property
    def solve_time_min(self) -> int | None:
        if self.solve_time_sec is None:
            return None
        return self.solve_time_sec // 60

    @property
    def status_emoji(self) -> str:
        if self.solved:
            return "✅"
        if self.wrong_attempts > 0:
            return "❌"
        return "⬜"

    @property
    def status_text(self) -> str:
        if self.solved:
            t = self.solve_time_min
            return f"✅ **{self.score}** pts ({t}m, {self.wrong_attempts} WA)"
        if self.wrong_attempts > 0:
            return f"❌ {self.wrong_attempts} WA"
        return "⬜ Pending"

    def to_dict(self) -> dict:
        return {
            "index": self.problem.index,
            "name": self.problem.name,
            "max_points": self.problem.max_points,
            "score": self.score,
            "time_min": self.solve_time_min,
            "wrong_attempts": self.wrong_attempts,
            "solved": self.solved,
        }


# ── Virtual contest session ───────────────────────────────────────────────

class VirtualContestSession:
    """Manages the entire lifecycle of a single virtual contest."""

    def __init__(
        self,
        bot: commands.Bot,
        user: discord.User,
        handle: str,
        contest: Contest,
        problems: list[ContestProblem],
        division: int,
        thread: discord.Thread | None,
        channel: discord.abc.Messageable,
    ):
        self.bot = bot
        self.user = user
        self.handle = handle
        self.contest = contest
        self.division = division
        self.thread = thread
        self.channel = channel
        self.target = thread or channel

        # Timing
        self.start_ts: int = int(time.time())
        self.duration_sec: int = contest.duration_seconds
        self.end_ts: int = self.start_ts + self.duration_sec
        self.ended: bool = False

        # Problem tracking
        self.trackers: list[ProblemTracker] = [ProblemTracker(p) for p in problems]

        # Dashboard message (will be set after posting)
        self.dashboard_msg: discord.Message | None = None

        # Polling task
        self._poll_task: asyncio.Task | None = None

    @property
    def elapsed_sec(self) -> int:
        return int(time.time()) - self.start_ts

    @property
    def remaining_sec(self) -> int:
        return max(0, self.end_ts - int(time.time()))

    @property
    def total_score(self) -> int:
        return sum(t.score for t in self.trackers)

    @property
    def total_solved(self) -> int:
        return sum(1 for t in self.trackers if t.solved)

    @property
    def all_solved(self) -> bool:
        return all(t.solved for t in self.trackers)

    # ── Dashboard embed ───────────────────────────────────────────────────

    def build_dashboard_embed(self) -> discord.Embed:
        duration_h = self.duration_sec // 3600
        duration_m = (self.duration_sec % 3600) // 60

        remaining = self.remaining_sec
        rem_h = remaining // 3600
        rem_m = (remaining % 3600) // 60
        rem_s = remaining % 60

        desc_lines = []
        for t in self.trackers:
            line = f"**{t.problem.index}** · [{t.problem.name}]({t.problem.url}) ({t.problem.max_points} pts)  —  {t.status_text}"
            desc_lines.append(line)

        embed = discord.Embed(
            title=f"🏆 Virtual Contest — {self.contest.name}",
            description="\n".join(desc_lines),
            color=config.COLOUR_WARN,
        )
        embed.add_field(
            name="📊 Current Score",
            value=f"**{self.total_score}** ({self.total_solved}/{len(self.trackers)} solved)",
            inline=True,
        )
        embed.add_field(
            name="⏰ Time Remaining",
            value=f"{rem_h}h {rem_m:02d}m {rem_s:02d}s",
            inline=True,
        )
        embed.add_field(
            name="📋 Division",
            value=f"Div. {self.division}",
            inline=True,
        )
        embed.set_footer(text=f"Contest ID: {self.contest.contest_id} • Polling every {POLL_INTERVAL}s")
        return embed

    # ── Results embed ─────────────────────────────────────────────────────

    def build_results_embed(
        self, est_rank: int | None = None, total_participants: int | None = None
    ) -> discord.Embed:
        # Problem table
        lines = ["```"]
        lines.append(f"{'Prob':>4} │ {'Score':>5} │ {'Time':>6} │ {'WA':>3} │ Status")
        lines.append(f"{'─'*4:>4}─┼─{'─'*5:>5}─┼─{'─'*6:>6}─┼─{'─'*3:>3}─┼─{'─'*8}")
        for t in self.trackers:
            time_str = f"{t.solve_time_min}m" if t.solve_time_min is not None else "—"
            if t.solved:
                status = "Solved"
            elif t.wrong_attempts > 0:
                status = "Failed"
            else:
                status = "Unsub"
            lines.append(
                f"{t.problem.index:>4} │ {t.score:>5} │ {time_str:>6} │ {t.wrong_attempts:>3} │ {status}"
            )
        lines.append("```")

        elapsed_min = self.elapsed_sec // 60

        desc = "\n".join(lines)
        desc += f"\n🏆 **Total Score:** {self.total_score}"
        desc += f"\n✅ **Solved:** {self.total_solved}/{len(self.trackers)}"
        desc += f"\n⏱️ **Time Used:** {elapsed_min} min"

        if est_rank is not None and total_participants:
            pct = format_rank_percentile(est_rank, total_participants)
            desc += f"\n\n📈 **Estimated Rank:** ~{est_rank:,} / {total_participants:,}"
            desc += f"\n📊 **{pct}**"

        embed = discord.Embed(
            title=f"📊 Virtual Contest Results — {self.contest.name}",
            description=desc,
            color=0x57F287 if self.total_solved > 0 else 0xED4245,
        )
        embed.set_footer(text=f"Div. {self.division} • Contest {self.contest.contest_id}")
        return embed

    # ── Polling loop ──────────────────────────────────────────────────────

    async def start_polling(self):
        """Start the background polling loop."""
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self):
        """Stop the polling loop."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        """Poll CF submissions every POLL_INTERVAL seconds."""
        try:
            while not self.ended and self.remaining_sec > 0:
                await asyncio.sleep(POLL_INTERVAL)
                if self.ended:
                    break

                try:
                    await self._check_submissions()
                except CFAPIError as e:
                    log.warning("Poll error for contest %d: %s", self.contest.contest_id, e)

                # Update dashboard
                if self.dashboard_msg:
                    try:
                        await self.dashboard_msg.edit(embed=self.build_dashboard_embed())
                    except discord.HTTPException:
                        pass

                # Auto-end if all solved
                if self.all_solved:
                    log.info("All problems solved, auto-ending contest %d", self.contest.contest_id)
                    break

            # Timer expired or all solved — end the contest
            if not self.ended:
                await self.end_contest()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Poll loop error: %s", e, exc_info=True)

    async def _check_submissions(self):
        """Check the user's CF submissions for all contest problems."""
        cf = self.bot.cf
        try:
            subs = await cf.get_user_submissions_for_contest(
                self.handle, self.contest.contest_id, after_ts=self.start_ts
            )
        except CFAPIError:
            return

        for tracker in self.trackers:
            if tracker.solved:
                continue  # Already accepted, skip

            # Filter submissions for this specific problem
            problem_subs = [
                s for s in subs
                if s.problem.index == tracker.problem.index
            ]

            if not problem_subs:
                continue

            wrong_count = 0
            for sub in sorted(problem_subs, key=lambda s: s.time_seconds):
                if sub.verdict is None:
                    # Still being judged, skip
                    continue
                if sub.is_accepted:
                    # Solved!
                    tracker.solved = True
                    tracker.solve_time_sec = sub.time_seconds - self.start_ts
                    tracker.wrong_attempts = wrong_count
                    # Calculate score
                    solve_min = tracker.solve_time_sec // 60
                    tracker.score = calculate_problem_score(
                        tracker.problem.max_points, solve_min, wrong_count
                    )
                    log.info(
                        "User %s solved %s in %dm with %d WA → %d pts",
                        self.handle, tracker.problem.index, solve_min,
                        wrong_count, tracker.score,
                    )
                    break
                else:
                    wrong_count += 1

            # Update wrong attempts count even if not yet solved
            if not tracker.solved:
                tracker.wrong_attempts = wrong_count

    # ── End contest ───────────────────────────────────────────────────────

    async def end_contest(self):
        """Finalise the contest: compute scores, estimate rank, save to DB."""
        if self.ended:
            return
        self.ended = True

        # Final poll to catch last-minute submissions
        try:
            await self._check_submissions()
        except Exception:
            pass

        # Fetch standings for rank estimation
        est_rank = None
        total_participants = None
        try:
            cf = self.bot.cf
            standings = await cf.get_contest_standings(self.contest.contest_id)
            if standings:
                est_rank, total_participants = estimate_rank(self.total_score, standings)
        except CFAPIError as e:
            log.warning("Could not fetch standings for rank: %s", e)

        # Build results embed
        results_embed = self.build_results_embed(est_rank, total_participants)

        # Post results
        await self.target.send(
            content=self.user.mention,
            embed=results_embed,
        )

        # Update dashboard to show "Contest Ended"
        if self.dashboard_msg:
            final_embed = self.build_dashboard_embed()
            final_embed.title = f"🏁 Contest Ended — {self.contest.name}"
            final_embed.color = 0x808080
            try:
                await self.dashboard_msg.edit(embed=final_embed, view=None)
            except discord.HTTPException:
                pass

        # Save to database
        problem_results_json = json.dumps([t.to_dict() for t in self.trackers])
        db = self.bot.db
        await q.record_virtual_contest(
            db,
            discord_id=self.user.id,
            contest_id=self.contest.contest_id,
            contest_name=self.contest.name,
            division=str(self.division),
            total_score=self.total_score,
            estimated_rank=est_rank,
            total_participants=total_participants,
            total_solved=self.total_solved,
            total_problems=len(self.trackers),
            duration_sec=self.elapsed_sec,
            problem_results=problem_results_json,
        )
        log.info(
            "Virtual contest %d ended for user %s: score=%d, rank=%s/%s",
            self.contest.contest_id, self.handle, self.total_score,
            est_rank, total_participants,
        )


# ── End Contest Early button ──────────────────────────────────────────────

class EndContestConfirmView(discord.ui.View):
    """Confirmation dialog before ending the contest early."""

    def __init__(self, session: VirtualContestSession):
        super().__init__(timeout=60)
        self.session = session

    @discord.ui.button(label="Yes, end contest", style=discord.ButtonStyle.danger, emoji="🏁")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.session.user.id:
            await interaction.response.send_message("This isn't your contest!", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="🏁 Ending contest...", view=None,
        )
        await self.session.stop_polling()
        await self.session.end_contest()
        self.stop()

    @discord.ui.button(label="No, keep going", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.session.user.id:
            await interaction.response.send_message("This isn't your contest!", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="Contest continues! 💪", view=None,
        )
        self.stop()


class ContestDashboardView(discord.ui.View):
    """Main view shown during the contest with an 'End Contest Early' button."""

    def __init__(self, session: VirtualContestSession):
        super().__init__(timeout=None)  # Persist until contest ends
        self.session = session

    @discord.ui.button(label="🏁 End Contest Early", style=discord.ButtonStyle.danger)
    async def end_early(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.session.user.id:
            await interaction.response.send_message("This isn't your contest!", ephemeral=True)
            return

        remaining = self.session.remaining_sec
        rem_m = remaining // 60

        confirm_view = EndContestConfirmView(self.session)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to end the contest? You still have **{rem_m} minutes** left!",
            view=confirm_view,
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────

class GitgudContest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track active sessions to prevent duplicates
        self._active_sessions: dict[int, VirtualContestSession] = {}

    @app_commands.command(
        name="gitgud_contest",
        description="Start a virtual Codeforces contest simulation.",
    )
    @app_commands.describe(
        division="Contest division (1–4)",
    )
    @app_commands.choices(division=[
        app_commands.Choice(name="Division 1", value=1),
        app_commands.Choice(name="Division 2", value=2),
        app_commands.Choice(name="Division 3", value=3),
        app_commands.Choice(name="Division 4", value=4),
    ])
    async def gitgud_contest(
        self,
        interaction: discord.Interaction,
        division: app_commands.Choice[int],
    ):
        await interaction.response.defer()

        user = interaction.user
        div = division.value
        db = self.bot.db
        cf = self.bot.cf

        # Check if user already has an active virtual contest
        if user.id in self._active_sessions:
            session = self._active_sessions[user.id]
            if not session.ended:
                await interaction.followup.send(
                    embed=error_embed(
                        f"You already have an active virtual contest!\n"
                        f"**{session.contest.name}** — {session.remaining_sec // 60}m remaining.\n\n"
                        f"End it first using the 🏁 button in the contest thread."
                    ),
                    ephemeral=True,
                )
                return

        # Check user is registered
        handle = await q.get_handle(db, user.id)
        if not handle:
            await interaction.followup.send(
                embed=error_embed("Use **/setup** first to link your Codeforces handle."),
                ephemeral=True,
            )
            return

        # Pick a contest
        try:
            contest = await pick_contest(cf, db, user.id, div)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        if not contest:
            await interaction.followup.send(
                embed=error_embed(f"No finished Div. {div} contests found."),
                ephemeral=True,
            )
            return

        # Fetch contest problems
        try:
            contest_data, problems = await cf.get_contest_problems(contest.contest_id)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        if not problems:
            await interaction.followup.send(
                embed=error_embed("Could not load problems for this contest. Try again."),
                ephemeral=True,
            )
            return

        # Use the fuller contest data from standings
        contest = contest_data

        # Create a thread
        channel = interaction.channel
        duration_h = contest.duration_seconds // 3600
        duration_m = (contest.duration_seconds % 3600) // 60
        thread_name = f"🏆 Virtual — {contest.name[:60]}"

        try:
            thread = await channel.create_thread(
                name=thread_name,
                auto_archive_duration=max(60, (contest.duration_seconds // 60) + 30),
                reason="gitgud virtual contest",
            )
        except (discord.Forbidden, AttributeError):
            thread = None

        # Create session
        session = VirtualContestSession(
            bot=self.bot,
            user=user,
            handle=handle,
            contest=contest,
            problems=problems,
            division=div,
            thread=thread,
            channel=channel,
        )
        self._active_sessions[user.id] = session

        # Create dashboard view
        view = ContestDashboardView(session)

        # Post the dashboard
        target = thread or channel
        dashboard_embed = session.build_dashboard_embed()
        msg = await target.send(embed=dashboard_embed, view=view)
        session.dashboard_msg = msg

        # Notify in the original channel if thread was created
        if thread:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🏆 Virtual Contest Started!",
                    description=(
                        f"**{contest.name}** (Div. {div})\n"
                        f"⏱️ Duration: {duration_h}h {duration_m}m\n"
                        f"📝 {len(problems)} problems\n\n"
                        f"Head to {thread.mention} to begin! ⚡\n\n"
                        f"Solve problems on CF and the bot will auto-detect your submissions."
                    ),
                    color=config.COLOUR_OK,
                )
            )
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"Virtual contest started! Solve problems on CF — submissions are auto-tracked. ⚡",
                    color=config.COLOUR_OK,
                )
            )

        # Start polling
        await session.start_polling()

        # Cleanup when done
        async def _cleanup():
            """Wait for session to end and clean up."""
            while not session.ended:
                await asyncio.sleep(10)
            # Remove from active sessions
            self._active_sessions.pop(user.id, None)
            # Disable the dashboard view
            if session.dashboard_msg:
                try:
                    for item in view.children:
                        item.disabled = True
                    await session.dashboard_msg.edit(view=view)
                except discord.HTTPException:
                    pass

        asyncio.create_task(_cleanup())


async def setup(bot: commands.Bot):
    await bot.add_cog(GitgudContest(bot))
