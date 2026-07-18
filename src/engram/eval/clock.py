# src/engram/eval/clock.py
"""Simulated time for lifecycle runs. Injected as Engram's `now`; the Keeper's
decay/prune math then runs on sim time, so weeks compress into milliseconds."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class SimClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, days: float = 0.0, seconds: float = 0.0) -> None:
        if days < 0 or seconds < 0:
            raise ValueError("SimClock only advances forward")
        self._now += timedelta(days=days, seconds=seconds)
