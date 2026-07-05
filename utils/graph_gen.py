"""
utils/graph_gen.py — matplotlib graph generators returning BytesIO PNGs
"""
from __future__ import annotations

import io
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import matplotlib
matplotlib.use("Agg")   # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from cf_api.models import Submission

# ── Common style ─────────────────────────────────────────────────────────

DARK_BG   = "#1e1f22"
DARK_AX   = "#2b2d31"
LINE_COL  = "#5865f2"   # Discord blurple
TEXT_COL  = "#dcddde"
GRID_COL  = "#3a3b3e"

def _apply_dark_style(fig: plt.Figure, ax: plt.Axes):
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_AX)
    ax.tick_params(colors=TEXT_COL)
    ax.xaxis.label.set_color(TEXT_COL)
    ax.yaxis.label.set_color(TEXT_COL)
    ax.title.set_color(TEXT_COL)
    ax.spines[:].set_color(GRID_COL)
    ax.grid(True, color=GRID_COL, linewidth=0.5, alpha=0.7)

def _fig_to_bytes(fig: plt.Figure) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

# ── Rating history graph ──────────────────────────────────────────────────

def generate_rating_graph(rating_changes: list[dict], handle: str) -> io.BytesIO:
    """
    rating_changes: list of CF ratingChange objects
    { ratingUpdateTimeSeconds: int, newRating: int, contestName: str }
    """
    if not rating_changes:
        raise ValueError("No rating change data available")

    times = [datetime.fromtimestamp(r["ratingUpdateTimeSeconds"], tz=timezone.utc) for r in rating_changes]
    ratings = [r["newRating"] for r in rating_changes]

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_dark_style(fig, ax)

    ax.plot(times, ratings, color=LINE_COL, linewidth=2, zorder=3)
    ax.fill_between(times, ratings, alpha=0.15, color=LINE_COL)

    # Colour bands (CF rating zones)
    zones = [
        (0, 1200, "#808080"),
        (1200, 1400, "#008000"),
        (1400, 1600, "#03a89e"),
        (1600, 1900, "#0000ff"),
        (1900, 2100, "#aa00aa"),
        (2100, 2400, "#ff8c00"),
        (2400, 4000, "#ff0000"),
    ]
    for lo, hi, col in zones:
        ax.axhspan(lo, hi, alpha=0.05, color=col, zorder=0)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    ax.set_title(f"Rating History — {handle}", fontsize=13, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Rating")

    return _fig_to_bytes(fig)

# ── Tag bar chart ─────────────────────────────────────────────────────────

def generate_tag_bar(submissions: list[Submission], handle: str, top_n: int = 15) -> io.BytesIO:
    """Bar chart of solved problems by tag (top N tags)."""
    tag_counter: Counter = Counter()
    for sub in submissions:
        if sub.is_accepted:
            for tag in sub.problem.tags:
                tag_counter[tag] += 1

    if not tag_counter:
        raise ValueError("No solved problems found")

    most_common = tag_counter.most_common(top_n)
    labels = [t for t, _ in most_common][::-1]
    values = [c for _, c in most_common][::-1]

    fig, ax = plt.subplots(figsize=(8, max(4, len(labels) * 0.4)))
    _apply_dark_style(fig, ax)

    bars = ax.barh(labels, values, color=LINE_COL, edgecolor=GRID_COL, height=0.6)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", color=TEXT_COL, fontsize=9)

    ax.set_title(f"Problems Solved by Tag — {handle}", fontsize=13, fontweight="bold")
    ax.set_xlabel("Count")
    ax.set_xlim(0, max(values) * 1.15)

    return _fig_to_bytes(fig)

# ── Submission heatmap ────────────────────────────────────────────────────

def generate_heatmap(submissions: list[Submission], handle: str) -> io.BytesIO:
    """GitHub-style contribution heatmap of submission days (last 52 weeks)."""
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(weeks=52)

    # Count submissions per day
    day_counts: Counter = Counter()
    for sub in submissions:
        dt = datetime.fromtimestamp(sub.time_seconds, tz=timezone.utc).date()
        if dt >= start:
            day_counts[dt] += 1

    # Build 52×7 grid
    weeks = 53
    grid = np.zeros((7, weeks), dtype=float)
    labels_week: list[str] = []

    for w in range(weeks):
        for d in range(7):
            day = start + timedelta(weeks=w, days=d)
            grid[d, w] = day_counts.get(day, 0)
        week_date = start + timedelta(weeks=w)
        labels_week.append(week_date.strftime("%b"))

    fig, ax = plt.subplots(figsize=(14, 3))
    _apply_dark_style(fig, ax)

    cmap = matplotlib.colormaps.get_cmap("YlGn")
    cmap.set_under(DARK_AX)

    im = ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0.5, vmax=max(day_counts.values() or [1]),
                   interpolation="nearest")

    # Sparse month labels on x-axis
    seen: set[str] = set()
    xticks, xlabels = [], []
    for i, lbl in enumerate(labels_week):
        if lbl not in seen:
            xticks.append(i)
            xlabels.append(lbl)
            seen.add(lbl)

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels, color=TEXT_COL, fontsize=8)
    ax.set_yticks([0, 1, 2, 3, 4, 5, 6])
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], color=TEXT_COL, fontsize=8)
    ax.set_title(f"Submission Heatmap — {handle} (last 52 weeks)", color=TEXT_COL, fontsize=12)

    fig.colorbar(im, ax=ax, orientation="vertical", pad=0.02, fraction=0.02, label="Submissions")

    return _fig_to_bytes(fig)
