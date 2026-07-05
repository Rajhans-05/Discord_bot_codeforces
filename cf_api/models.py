"""
cf_api/models.py — Typed dataclasses for Codeforces API objects
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Problem:
    contest_id: int
    index: str          # e.g. "A", "B", "C1"
    name: str
    rating: Optional[int]       # None if unrated
    tags: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://codeforces.com/problemset/problem/{self.contest_id}/{self.index}"

    @property
    def display_id(self) -> str:
        return f"{self.contest_id}{self.index}"

    @classmethod
    def from_api(cls, data: dict) -> "Problem":
        return cls(
            contest_id=data.get("contestId", 0),
            index=data.get("index", ""),
            name=data.get("name", ""),
            rating=data.get("rating"),
            tags=data.get("tags", []),
        )

@dataclass
class Submission:
    sub_id: int
    problem: Problem
    verdict: Optional[str]      # "OK", "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", etc.
    time_seconds: int           # Unix timestamp
    author_handle: str

    @property
    def is_accepted(self) -> bool:
        return self.verdict == "OK"

    @classmethod
    def from_api(cls, data: dict) -> "Submission":
        return cls(
            sub_id=data.get("id", 0),
            problem=Problem.from_api(data.get("problem", {})),
            verdict=data.get("verdict"),
            time_seconds=data.get("creationTimeSeconds", 0),
            author_handle=data.get("author", {}).get("members", [{}])[0].get("handle", ""),
        )

@dataclass
class CFUser:
    handle: str
    rating: Optional[int]
    max_rating: Optional[int]
    rank: Optional[str]
    max_rank: Optional[str]
    contribution: int = 0
    friend_of_count: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "CFUser":
        return cls(
            handle=data.get("handle", ""),
            rating=data.get("rating"),
            max_rating=data.get("maxRating"),
            rank=data.get("rank"),
            max_rank=data.get("maxRank"),
            contribution=data.get("contribution", 0),
            friend_of_count=data.get("friendOfCount", 0),
        )

@dataclass
class Contest:
    contest_id: int
    name: str
    phase: str              # "BEFORE", "CODING", "FINISHED"
    start_time_seconds: int
    duration_seconds: int

    @property
    def url(self) -> str:
        return f"https://codeforces.com/contest/{self.contest_id}"

    @classmethod
    def from_api(cls, data: dict) -> "Contest":
        return cls(
            contest_id=data.get("id", 0),
            name=data.get("name", ""),
            phase=data.get("phase", ""),
            start_time_seconds=data.get("startTimeSeconds", 0),
            duration_seconds=data.get("durationSeconds", 0),
        )
