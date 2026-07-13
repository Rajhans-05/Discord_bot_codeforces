"""
cogs/gimme.py — /gimme: problem recommender (random or latest unsolved)
"""
from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

import db.queries as q
from cf_api.client import CFAPIError
from utils.embed_builder import error_embed, problem_embed

log = logging.getLogger(__name__)

CF_TAGS = [
    "2-sat", "binary search", "bitmasks", "brute force", "chinese remainder theorem",
    "combinatorics", "constructive algorithms", "data structures", "dfs and similar",
    "divide and conquer", "dp", "dsu", "expression parsing", "fft", "flows",
    "games", "geometry", "graph matchings", "graphs", "greedy", "hashing",
    "implementation", "interactive", "math", "matrices", "meet-in-the-middle",
    "number theory", "probabilities", "schedules", "shortest paths", "sortings",
    "string suffix structures", "strings", "ternary search", "trees", "two pointers",
]

CF_RATINGS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700,
              1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800, 3000, 3200, 3500]

# Preset rating options: (display_name, value_string)
RATING_OPTIONS = [
    ("⭐ Any rating",       "any"),
    ("🟢 800 – 1000",      "800-1000"),
    ("🟢 1000 – 1500",     "1000-1500"),
    ("🟡 1500 – 2000",     "1500-2000"),
    ("🟠 2000 – 2500",     "2000-2500"),
    ("🔴 2500 – 3500",     "2500-3500"),
]

async def tag_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    # Split on commas to support multi-tag input like "dp, graphs, bitmasks"
    parts = [p.strip().lower() for p in current.split(",")]
    # Tags already selected (all parts except the one being typed)
    already_selected = set(parts[:-1])
    # The fragment the user is currently typing (after the last comma)
    fragment = parts[-1] if parts else ""
    # Build the prefix string from already-selected tags
    prefix = ", ".join(p for p in parts[:-1] if p) + (", " if already_selected - {""} else "")

    # Filter: match the fragment, exclude already-selected tags
    available = [t for t in CF_TAGS if t not in already_selected and fragment in t]

    choices: list[app_commands.Choice[str]] = []
    for tag in available[:25]:
        full_value = f"{prefix}{tag}"
        # Discord limits Choice name/value to 100 chars
        if len(full_value) <= 100:
            choices.append(app_commands.Choice(name=full_value, value=full_value))

    return choices

async def rating_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    lower = current.strip().lower()
    choices: list[app_commands.Choice[str]] = []

    # Show preset ranges that match the typed text
    for display, value in RATING_OPTIONS:
        if lower in display.lower() or lower in value:
            choices.append(app_commands.Choice(name=display, value=value))

    # Also show exact ratings that match
    for r in CF_RATINGS:
        if str(r).startswith(lower) or not lower:
            if len(choices) < 25:
                choices.append(app_commands.Choice(name=f"Exact: {r}", value=str(r)))

    return choices[:25]

class Gimme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="gimme",
        description="Get a Codeforces problem recommendation.",
    )
    @app_commands.describe(
        mode="random: any problem | latest_unsolved: newest unAC'd problem",
        rating="Rating filter: 'any', a range like '1000-1500', or exact like '1600'",
        tags="Comma-separated tags (e.g. dp,graphs)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="🎲 Random unsolved", value="random"),
        app_commands.Choice(name="🕐 Latest unsolved (newest first)", value="latest_unsolved"),
    ])
    @app_commands.autocomplete(tags=tag_autocomplete, rating=rating_autocomplete)
    async def gimme(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        rating: str,
        tags: str = "",
    ):
        await interaction.response.defer()

        db = self.bot.db   
        cf = self.bot.cf   

        handle = await q.get_handle(db, interaction.user.id)
        if not handle:
            await interaction.followup.send(
                embed=error_embed("You haven't linked a Codeforces handle yet.\nUse **/setup** first."),
                ephemeral=True,
            )
            return

        # Parse the rating filter
        rating_raw = rating.strip().lower()
        rating_min: int | None = None
        rating_max: int | None = None
        exact_rating: int | None = None
        rating_label = "any rating"

        if rating_raw == "any":
            pass  # no rating filter
        elif "-" in rating_raw:
            # Range like "1000-1500"
            try:
                lo, hi = rating_raw.split("-", 1)
                rating_min, rating_max = int(lo), int(hi)
                rating_label = f"{rating_min} – {rating_max}"
            except ValueError:
                await interaction.followup.send(
                    embed=error_embed(
                        f"**{rating}** is not a valid rating filter.\n"
                        f"Use **any**, a range like **1000-1500**, or an exact rating like **1600**."
                    ),
                    ephemeral=True,
                )
                return
        else:
            # Exact rating like "1600"
            try:
                exact_rating = int(rating_raw)
                rating_label = str(exact_rating)
            except ValueError:
                await interaction.followup.send(
                    embed=error_embed(
                        f"**{rating}** is not a valid rating filter.\n"
                        f"Use **any**, a range like **1000-1500**, or an exact rating like **1600**."
                    ),
                    ephemeral=True,
                )
                return

            if exact_rating not in CF_RATINGS:
                closest = min(CF_RATINGS, key=lambda r: abs(r - exact_rating))
                await interaction.followup.send(
                    embed=error_embed(
                        f"**{exact_rating}** is not a standard CF rating.\n"
                        f"Closest valid rating: **{closest}**. Try that instead."
                    ),
                    ephemeral=True,
                )
                return

        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []

        try:
            solved = await cf.get_solved_problems(handle)
            all_problems = await cf.get_problemset(tag_list if tag_list else None)
        except CFAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return

        # Apply rating filter
        if exact_rating is not None:
            candidates = [p for p in all_problems if p.rating == exact_rating and p.display_id not in solved]
        elif rating_min is not None and rating_max is not None:
            candidates = [p for p in all_problems if p.rating is not None and rating_min <= p.rating <= rating_max and p.display_id not in solved]
        else:
            # "any" — no rating filter
            candidates = [p for p in all_problems if p.display_id not in solved]

        if tag_list:
            tag_set = set(tag_list)
            candidates = [p for p in candidates if tag_set.issubset(set(p.tags))]

        if not candidates:
            await interaction.followup.send(
                embed=error_embed(
                    f"No unsolved problems found at rating **{rating_label}**"
                    + (f" with tags **{', '.join(tag_list)}**" if tag_list else "")
                    + ".\nTry different filters!"
                ),
            )
            return

        mode_val = mode.value if isinstance(mode, app_commands.Choice) else mode

        if mode_val == "random":
            
            candidates.sort(key=lambda p: (p.contest_id, -ord(p.index[0]) if p.index else 0), reverse=True)
            problem = random.choice(candidates[:100])
            title = "🎲 Random Recommendation"
        else:
            
            candidates.sort(key=lambda p: (p.contest_id, -ord(p.index[0]) if p.index else 0), reverse=True)
            problem = candidates[0]
            title = "🕐 Latest Unsolved Problem"

        embed = problem_embed(problem, title=title)
        embed.set_footer(text=f"Handle: {handle}  •  Solved {len(solved)} problems total")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Gimme(bot))
