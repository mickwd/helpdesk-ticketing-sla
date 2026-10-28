"""Cálculo puro de SLA en horario hábil.

Este módulo no conoce la base de datos ni FastAPI: recibe datetimes aware,
un calendario y los intervalos de pausa, y devuelve el estado del SLA.
Toda la aritmética de horas hábiles (fines de semana, feriados, pausas por
"en espera del usuario") vive acá para poder testearla de forma aislada.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} debe tener zona horaria")


class Calendar(Protocol):
    def business_seconds(self, start: datetime, end: datetime) -> float: ...

    def add_business_seconds(self, start: datetime, seconds: float) -> datetime: ...


class AlwaysOnCalendar:
    """Calendario 24x7: cada segundo cuenta (usado típicamente para P1)."""

    def business_seconds(self, start: datetime, end: datetime) -> float:
        _require_aware(start, "start")
        _require_aware(end, "end")
        return max((end - start).total_seconds(), 0.0)

    def add_business_seconds(self, start: datetime, seconds: float) -> datetime:
        _require_aware(start, "start")
        return start + timedelta(seconds=max(seconds, 0.0))


@dataclass(frozen=True)
class BusinessHoursCalendar:
    """Horario hábil con jornada diaria, días laborables y feriados."""

    tz: ZoneInfo
    opens_at: time = time(9, 0)
    closes_at: time = time(18, 0)
    workdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})  # lunes=0 … viernes=4
    holidays: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        if self.opens_at >= self.closes_at:
            raise ValueError("La hora de apertura debe ser anterior a la de cierre")
        if not self.workdays:
            raise ValueError("El calendario necesita al menos un día laborable")

    def is_business_day(self, day: date) -> bool:
        return day.weekday() in self.workdays and day not in self.holidays

    def _window(self, day: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(day, self.opens_at, tzinfo=self.tz),
            datetime.combine(day, self.closes_at, tzinfo=self.tz),
        )

    def business_seconds(self, start: datetime, end: datetime) -> float:
        _require_aware(start, "start")
        _require_aware(end, "end")
        if end <= start:
            return 0.0
        local_start = start.astimezone(self.tz)
        local_end = end.astimezone(self.tz)
        total = 0.0
        day = local_start.date()
        while day <= local_end.date():
            if self.is_business_day(day):
                open_dt, close_dt = self._window(day)
                seg_start = max(local_start, open_dt)
                seg_end = min(local_end, close_dt)
                if seg_end > seg_start:
                    total += (seg_end - seg_start).total_seconds()
            day += timedelta(days=1)
        return total

    def add_business_seconds(self, start: datetime, seconds: float) -> datetime:
        _require_aware(start, "start")
        remaining = max(seconds, 0.0)
        if remaining == 0:
            return start
        cursor = start.astimezone(self.tz)
        while True:
            day = cursor.date()
            open_dt, close_dt = self._window(day)
            if not self.is_business_day(day) or cursor >= close_dt:
                cursor = self._next_opening(day)
                continue
            if cursor < open_dt:
                cursor = open_dt
            available = (close_dt - cursor).total_seconds()
            if remaining <= available:
                return (cursor + timedelta(seconds=remaining)).astimezone(UTC)
            remaining -= available
            cursor = self._next_opening(day)

    def _next_opening(self, day: date) -> datetime:
        nxt = day + timedelta(days=1)
        for _ in range(3660):  # protección ante calendarios con feriados infinitos
            if self.is_business_day(nxt):
                return self._window(nxt)[0]
            nxt += timedelta(days=1)
        raise ValueError("El calendario no tiene días hábiles en los próximos 10 años")


@dataclass(frozen=True)
class Pause:
    """Intervalo en el que el reloj está detenido. end=None significa pausa en curso."""

    start: datetime
    end: datetime | None = None


def merge_pauses(pauses: Iterable[Pause]) -> list[Pause]:
    """Ordena y une pausas superpuestas para no descontar dos veces el mismo tramo."""
    ordered = sorted(pauses, key=lambda p: p.start)
    merged: list[Pause] = []
    for pause in ordered:
        if pause.end is not None and pause.end <= pause.start:
            continue
        if merged:
            last = merged[-1]
            if last.end is None:
                break  # una pausa abierta absorbe todo lo posterior
            if pause.start <= last.end:
                new_end = None if pause.end is None else max(last.end, pause.end)
                merged[-1] = Pause(last.start, new_end)
                continue
        merged.append(pause)
    return merged


def elapsed_business_seconds(
    calendar: Calendar,
    start: datetime,
    end: datetime,
    pauses: Sequence[Pause] = (),
) -> float:
    """Segundos hábiles transcurridos entre start y end descontando las pausas."""
    if end <= start:
        return 0.0
    total = calendar.business_seconds(start, end)
    for pause in merge_pauses(pauses):
        p_start = max(pause.start, start)
        p_end = min(pause.end or end, end)
        if p_end > p_start:
            total -= calendar.business_seconds(p_start, p_end)
    return max(total, 0.0)


def compute_due_at(
    calendar: Calendar,
    start: datetime,
    target_seconds: float,
    pauses: Sequence[Pause] = (),
) -> datetime | None:
    """Vencimiento considerando pausas.

    Devuelve None si hay una pausa abierta antes de consumir el objetivo,
    porque mientras el ticket espera al usuario no se puede saber cuándo vence.
    """
    remaining = float(target_seconds)
    cursor = start
    for pause in merge_pauses(pauses):
        if pause.end is not None and pause.end <= cursor:
            continue
        p_start = max(pause.start, cursor)
        segment = calendar.business_seconds(cursor, p_start)
        if segment >= remaining:
            return calendar.add_business_seconds(cursor, remaining)
        remaining -= segment
        if pause.end is None:
            return None
        cursor = pause.end
    return calendar.add_business_seconds(cursor, remaining)


class SlaState(StrEnum):
    EN_CURSO = "en_curso"
    ADVERTENCIA = "advertencia"
    INCUMPLIDO = "incumplido"
    PAUSADO = "pausado"
    CUMPLIDO = "cumplido"


@dataclass(frozen=True)
class SlaStatus:
    target_seconds: float
    elapsed_seconds: float
    remaining_seconds: float
    percent: float
    due_at: datetime | None
    paused: bool
    breached: bool
    stopped: bool
    state: SlaState


def evaluate_sla(
    calendar: Calendar,
    start: datetime,
    target_seconds: float,
    now: datetime,
    pauses: Sequence[Pause] = (),
    stopped_at: datetime | None = None,
    warning_threshold: float = 0.75,
) -> SlaStatus:
    """Evalúa un SLA (primera respuesta o resolución).

    - stopped_at: momento en que el objetivo se cumplió (primera respuesta o
      resolución). Si está presente, el reloj deja de correr ahí.
    - warning_threshold: fracción del objetivo a partir de la cual se advierte.
    """
    if target_seconds <= 0:
        raise ValueError("El objetivo de SLA debe ser positivo")
    end = stopped_at or now
    elapsed = elapsed_business_seconds(calendar, start, end, pauses)
    remaining = target_seconds - elapsed
    percent = elapsed / target_seconds
    breached = elapsed > target_seconds
    paused = stopped_at is None and any(
        p.end is None and p.start <= now for p in merge_pauses(pauses)
    )
    due_at = compute_due_at(calendar, start, target_seconds, pauses)

    if stopped_at is not None:
        state = SlaState.INCUMPLIDO if breached else SlaState.CUMPLIDO
    elif breached:
        state = SlaState.INCUMPLIDO
    elif paused:
        state = SlaState.PAUSADO
    elif percent >= warning_threshold:
        state = SlaState.ADVERTENCIA
    else:
        state = SlaState.EN_CURSO

    return SlaStatus(
        target_seconds=float(target_seconds),
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
        percent=round(percent, 4),
        due_at=due_at,
        paused=paused,
        breached=breached,
        stopped=stopped_at is not None,
        state=state,
    )
