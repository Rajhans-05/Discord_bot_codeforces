"""
utils/contest_picker.py — Smart priority-based contest selection for virtual contests

Priority order:
  1. Unattempted contests (never done a virtual on this bot)  — HIGHEST
  2. Attempted contests with fewer problems solved             — MEDIUM
  3. Attempted contests with more problems solved              — LOWEST

Within each tier, pick randomly for variety.
"""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite
    from cf_api.client import CodeforcesClient
    from cf_api.models import Contest

import db.queries as q

log = logging.getLogger(__name__)


async def pick_contest(
    cf: "CodeforcesClient",
    db: "aiosqlite.Connection",
    discord_id: int,
    division: int,
) -> "Contest | None":
    """
    Pick a contest for the user, prioritised so that fresh challenges come first.

    Returns None if no contests are available for that division.
    """
    # 1. Fetch all finished contests for this division
    contests = await cf.get_finished_div_contests(division)
    if not contests:
        return None

    # 2. Get user's virtual contest history
    history = await q.get_user_virtual_history(db, discord_id)

    # Build a map:  contest_id → total_solved
    history_map: dict[int, int] = {}
    for row in history:
        cid = row["contest_id"]
        solved = row["total_solved"]
        # Keep the maximum total_solved if they've done the same contest multiple times
        if cid not in history_map or solved > history_map[cid]:
            history_map[cid] = solved

    # 3. Partition into tiers
    tier1_unattempted: list[Contest] = []
    tier2_few_solved: list[tuple[int, Contest]] = []   # (total_solved, contest)

    for c in contests:
        if c.contest_id not in history_map:
            tier1_unattempted.append(c)
        else:
            tier2_few_solved.append((history_map[c.contest_id], c))

    # 4. Pick from highest priority tier available
    if tier1_unattempted:
        chosen = random.choice(tier1_unattempted)
        log.info("Picked unattempted contest %d for user %d", chosen.contest_id, discord_id)
        return chosen

    if tier2_few_solved:
        # Sort ascending by total_solved (fewer solved = higher priority)
        tier2_few_solved.sort(key=lambda x: x[0])
        # Pick from the least-solved group
        min_solved = tier2_few_solved[0][0]
        candidates = [c for solved, c in tier2_few_solved if solved == min_solved]
        chosen = random.choice(candidates)
        log.info(
            "Picked least-attempted contest %d (solved %d) for user %d",
            chosen.contest_id, min_solved, discord_id,
        )
        return chosen

    # Shouldn't reach here since tier2 would cover all history entries,
    # but just in case — pick any random contest
    return random.choice(contests) if contests else None
