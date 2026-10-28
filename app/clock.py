"""Reloj inyectable: permite congelar el tiempo en tests sin usar sleeps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Reloj controlable manualmente. Siempre devuelve datetimes en UTC."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FrozenClock requiere un datetime con zona horaria")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value.astimezone(UTC)

    def advance(self, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now
