"""Counts the characters sent to Google, because Google reports no usage figures itself.

The count is kept per calendar month (UTC) and survives restarts. It is an estimate: it knows
nothing about translations made with the same key elsewhere, but it is exact for everything this
integration sent, which is what the monthly budget is meant to protect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class Storage(Protocol):
    """The small part of Home Assistant's ``Store`` that is used."""

    async def async_load(self) -> Any: ...

    async def async_save(self, data: Any) -> None: ...

    def async_delay_save(self, data_func: Callable[[], Any], delay: float = ...) -> None: ...


@dataclass(frozen=True)
class Usage:
    """The characters used in the current month and the budget for it."""

    character_count: int
    character_limit: int | None
    period_start: str
    period_end: str

    @property
    def is_unlimited(self) -> bool:
        """Whether no monthly budget is set."""
        return not self.character_limit

    @property
    def characters_remaining(self) -> int | None:
        """Characters left in the budget, or None without one."""
        if self.is_unlimited:
            return None
        return max(self.character_limit - self.character_count, 0)

    @property
    def usage_percent(self) -> float | None:
        """Share of the budget that is used up, or None without one."""
        if self.is_unlimited:
            return None
        return round(self.character_count / self.character_limit * 100, 1)


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """First instant of the month of ``now`` and of the month after it."""
    start = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        following = start.replace(year=start.year + 1, month=1)
    else:
        following = start.replace(month=start.month + 1)
    return start, following


class UsageTracker:
    """Keeps the monthly character count of one account."""

    SAVE_DELAY = 30  # seconds; bursts of translations are written to disk once

    def __init__(
        self,
        storage: Storage,
        monthly_limit: int | None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._storage = storage
        self._limit = monthly_limit or None
        self._now = now
        self._period = month_bounds(now())[0].strftime("%Y-%m")
        self._count = 0
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        """Restore the count of the current month."""
        stored = await self._storage.async_load()
        if isinstance(stored, dict) and stored.get("period") == self._period:
            self._count = int(stored.get("characters", 0))

    async def async_flush(self) -> None:
        """Write the count now; delayed saves are only written when Home Assistant stops."""
        await self._storage.async_save(self._snapshot())

    @property
    def usage(self) -> Usage:
        """The current figures; a new month starts from zero."""
        self._roll_over()
        start, end = month_bounds(self._now())
        return Usage(self._count, self._limit, start.isoformat(), end.isoformat())

    def add(self, characters: int) -> None:
        """Count characters that were sent to Google."""
        self._roll_over()
        self._count += max(characters, 0)
        self._storage.async_delay_save(self._snapshot, self.SAVE_DELAY)
        self._notify()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` whenever the figures change; returns the way to stop."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def refresh(self) -> None:
        """Tell the listeners to look again, for example after the month has changed."""
        self._roll_over()
        self._notify()

    def _roll_over(self) -> None:
        period = month_bounds(self._now())[0].strftime("%Y-%m")
        if period != self._period:
            self._period, self._count = period, 0

    def _snapshot(self) -> dict[str, Any]:
        return {"period": self._period, "characters": self._count}

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
