"""
cf_api/client.py — Async Codeforces API wrapper with rate-limiting and caching
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import string
import time
from typing import Optional

import aiohttp

from cf_api.models import CFUser, Contest, Problem, Submission

log = logging.getLogger(__name__)

CF_BASE = "https://codeforces.com/api"
_RATE_LIMIT = 5          # max requests per second (CF allows 5/s)
_MIN_INTERVAL = 1.0 / _RATE_LIMIT

class CodeforcesClient:
    """
    Async HTTP client for the public Codeforces API.

    Usage:
        client = CodeforcesClient()
        await client.start()
        ...
        await client.close()
    """

    def __init__(self, api_key: str = "", api_secret: str = "", cache_ttl: int = 21600):
        self._api_key = api_key
        self._api_secret = api_secret
        self._cache_ttl = cache_ttl
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self._last_call = 0.0

        # Problem list cache
        self._problem_cache: list[Problem] = []
        self._problem_cache_time: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self):
        self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session:
            await self._session.close()

    # ── Rate-limited request ──────────────────────────────────────────────

    async def _request(self, method: str, params: dict | None = None) -> dict:
        """Make a rate-limited GET request to the CF API."""
        if params is None:
            params = {}

        # Inject auth if keys provided
        if self._api_key and self._api_secret:
            params = self._sign(method, params)

        async with self._lock:
            # Enforce rate limit
            elapsed = time.monotonic() - self._last_call
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_call = time.monotonic()

        url = f"{CF_BASE}/{method}"
        assert self._session is not None, "Call client.start() first"

        for attempt in range(3):
            try:
                async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("status") == "OK":
                        return data["result"]
                    comment = data.get("comment", "Unknown error")
                    log.warning("CF API error on %s: %s", method, comment)
                    if "limit" in comment.lower():
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise CFAPIError(comment)
            except aiohttp.ClientError as exc:
                log.error("HTTP error on attempt %d: %s", attempt + 1, exc)
                if attempt == 2:
                    raise
                await asyncio.sleep(1.5 ** attempt)

        raise CFAPIError("Max retries exceeded")

    def _sign(self, method: str, params: dict) -> dict:
        """Add HMAC-SHA512 signature to params (required for authenticated endpoints)."""
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        params["apiKey"] = self._api_key
        params["time"] = int(time.time())
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        to_hash = f"{rand}/{method}?{sorted_params}#{self._api_secret}"
        sig = hashlib.sha512(to_hash.encode()).hexdigest()
        params["apiSig"] = f"{rand}{sig}"
        return params

    # ── Public API methods ────────────────────────────────────────────────

    async def get_user_info(self, handles: list[str]) -> list[CFUser]:
        """Fetch user info for one or more handles."""
        result = await self._request("user.info", {"handles": ";".join(handles)})
        return [CFUser.from_api(u) for u in result]

    async def get_user_submissions(self, handle: str, count: int = 10000) -> list[Submission]:
        """Fetch latest `count` submissions for a user, newest first."""
        result = await self._request("user.status", {"handle": handle, "from": 1, "count": count})
        return [Submission.from_api(s) for s in result]

    async def get_problemset(self, tags: list[str] | None = None) -> list[Problem]:
        """
        Return the full CF problemset (or filtered by tags).
        Results are cached for `cache_ttl` seconds.
        """
        now = time.monotonic()
        if self._problem_cache and (now - self._problem_cache_time) < self._cache_ttl:
            problems = self._problem_cache
        else:
            # Always fetch the full problemset to avoid caching a partial list
            result = await self._request("problemset.problems", {})
            problems = [Problem.from_api(p) for p in result.get("problems", [])]
            self._problem_cache = problems
            self._problem_cache_time = now
            log.info("CF problem cache refreshed: %d problems", len(problems))

        # Filter by tags in-memory
        if tags:
            tag_set = set(tags)
            problems = [p for p in problems if tag_set.issubset(set(p.tags))]

        return problems

    async def get_contests(self, gym: bool = False) -> list[Contest]:
        """Return all contests (future + past). Filter phase == 'BEFORE' for upcoming."""
        result = await self._request("contest.list", {"gym": str(gym).lower()})
        return [Contest.from_api(c) for c in result]

    async def get_upcoming_contests(self) -> list[Contest]:
        """Return only contests that haven't started yet, sorted soonest-first."""
        contests = await self.get_contests()
        upcoming = [c for c in contests if c.phase == "BEFORE"]
        upcoming.sort(key=lambda c: c.start_time_seconds)
        return upcoming

    async def get_solved_problems(self, handle: str) -> set[str]:
        """
        Return a set of problem IDs (e.g. '1234A') that the user has AC'd.
        """
        subs = await self.get_user_submissions(handle)
        return {s.problem.display_id for s in subs if s.is_accepted}

    async def get_unsolved_attempted(self, handle: str) -> list[Submission]:
        """
        Return submissions for problems that were attempted but NEVER accepted.
        Sorted newest-first (API already returns newest-first).
        """
        subs = await self.get_user_submissions(handle)
        accepted = {s.problem.display_id for s in subs if s.is_accepted}
        seen: set[str] = set()
        result: list[Submission] = []
        for sub in subs:
            pid = sub.problem.display_id
            if pid in accepted or pid in seen:
                continue
            if sub.verdict is not None and sub.verdict != "OK":
                seen.add(pid)
                result.append(sub)
        return result  # already newest-first

class CFAPIError(Exception):
    pass
