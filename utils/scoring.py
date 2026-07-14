"""
utils/scoring.py — Codeforces scoring formula and rank estimation
"""
from __future__ import annotations

import bisect
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cf_api.models import StandingRow


def calculate_problem_score(
    max_points: int, time_minutes: int, wrong_attempts: int
) -> int:
    """
    Official Codeforces standard scoring formula:

        score = max(3*max_points/10,  max_points - max_points/250*t - 50*wrong_attempts)

    Where:
        t             = minutes from contest start to accepted submission
        wrong_attempts = number of wrong submissions before the AC

    Returns 0 if the problem was not solved (caller should check).
    """
    decay = max_points - (max_points / 250) * time_minutes - 50 * wrong_attempts
    floor = (3 * max_points) / 10
    return max(int(floor), int(decay))


def estimate_rank(
    user_total: float, standings: list[StandingRow]
) -> tuple[int, int]:
    """
    Estimate where a user's total score would place them in the real standings.

    Uses binary search on descending-sorted scores.
    Returns (estimated_rank, total_participants).

    Example: if standings have scores [3000, 2500, 2000, 1500, 1000]
             and user_total = 1800, estimated_rank = 3 (after 3000, 2500).
    """
    if not standings:
        return 1, 0

    total_participants = len(standings)

    # Standings are sorted by rank (ascending), so scores are descending
    scores = [row.total_points for row in standings]

    # Find the first position where user_total would be >= the score at that position
    # Since scores are descending, we want the first index where scores[i] < user_total
    rank = 1
    for i, score in enumerate(scores):
        if user_total >= score:
            rank = i + 1
            break
        rank = i + 2  # after all checked so far

    return rank, total_participants


def format_rank_percentile(rank: int, total: int) -> str:
    """Format rank as a percentile string like 'Top 6.8%'."""
    if total == 0:
        return "N/A"
    percentile = (rank / total) * 100
    if percentile <= 1:
        return f"Top {percentile:.2f}%"
    elif percentile <= 10:
        return f"Top {percentile:.1f}%"
    else:
        return f"Top {percentile:.0f}%"
