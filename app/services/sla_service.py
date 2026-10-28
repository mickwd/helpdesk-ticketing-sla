"""Puente entre el cálculo puro de SLA y los tickets persistidos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import Priority
from app.domain.sla import (
    AlwaysOnCalendar,
    BusinessHoursCalendar,
    Calendar,
    Pause,
    SlaStatus,
    evaluate_sla,
)
from app.models import SlaPolicy, Ticket


@dataclass(frozen=True)
class PolicyConfig:
    priority: Priority
    first_response_minutes: int
    resolution_minutes: int
    business_hours_only: bool = True
    description: str = ""


@dataclass(frozen=True)
class SlaConfig:
    timezone: str
    calendar: BusinessHoursCalendar
    warning_threshold: float
    policies: dict[Priority, PolicyConfig] = field(default_factory=dict)


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def parse_sla_config(raw: dict[str, Any]) -> SlaConfig:
    tz = ZoneInfo(raw.get("timezone", "America/Argentina/Buenos_Aires"))
    hours = raw.get("business_hours", {})
    holidays = frozenset(
        h if isinstance(h, date) else date.fromisoformat(str(h)) for h in raw.get("holidays", [])
    )
    calendar = BusinessHoursCalendar(
        tz=tz,
        opens_at=_parse_time(hours.get("start", "09:00")),
        closes_at=_parse_time(hours.get("end", "18:00")),
        workdays=frozenset(hours.get("workdays", [0, 1, 2, 3, 4])),
        holidays=holidays,
    )
    policies = {
        Priority(key): PolicyConfig(
            priority=Priority(key),
            first_response_minutes=int(value["first_response_minutes"]),
            resolution_minutes=int(value["resolution_minutes"]),
            business_hours_only=bool(value.get("business_hours_only", True)),
            description=str(value.get("description", "")),
        )
        for key, value in raw.get("policies", {}).items()
    }
    missing = set(Priority) - set(policies)
    if missing:
        raise ValueError(f"Faltan políticas de SLA para: {sorted(missing)}")
    return SlaConfig(
        timezone=str(tz),
        calendar=calendar,
        warning_threshold=float(raw.get("warning_threshold", 0.75)),
        policies=policies,
    )


@lru_cache(maxsize=8)
def load_sla_config(path: Path) -> SlaConfig:
    with Path(path).open(encoding="utf-8") as fh:
        return parse_sla_config(yaml.safe_load(fh))


@dataclass(frozen=True)
class TicketSla:
    response: SlaStatus
    resolution: SlaStatus


class SlaEngine:
    """Calcula el estado de SLA de un ticket con la política de su prioridad."""

    def __init__(self, config: SlaConfig, policies: dict[Priority, PolicyConfig] | None = None):
        self.config = config
        self.policies = policies or config.policies
        self._always_on = AlwaysOnCalendar()

    @classmethod
    def from_session(cls, config: SlaConfig, session: Session) -> SlaEngine:
        """Las políticas guardadas en la base (editables) tienen prioridad sobre el YAML."""
        rows = session.scalars(select(SlaPolicy)).all()
        policies = dict(config.policies)
        for row in rows:
            policies[row.priority] = PolicyConfig(
                priority=row.priority,
                first_response_minutes=row.first_response_minutes,
                resolution_minutes=row.resolution_minutes,
                business_hours_only=row.business_hours_only,
                description=row.description,
            )
        return cls(config, policies)

    @property
    def warning_threshold(self) -> float:
        return self.config.warning_threshold

    def policy_for(self, priority: Priority) -> PolicyConfig:
        return self.policies[Priority(priority)]

    def calendar_for(self, priority: Priority) -> Calendar:
        policy = self.policy_for(priority)
        return self.config.calendar if policy.business_hours_only else self._always_on

    @staticmethod
    def pauses_of(ticket: Ticket) -> list[Pause]:
        return [Pause(p.started_at, p.ended_at) for p in ticket.pauses]

    def response_status(self, ticket: Ticket, now: datetime) -> SlaStatus:
        policy = self.policy_for(ticket.priority)
        return evaluate_sla(
            self.calendar_for(ticket.priority),
            start=ticket.created_at,
            target_seconds=policy.first_response_minutes * 60,
            now=now,
            pauses=self.pauses_of(ticket),
            stopped_at=ticket.first_responded_at,
            warning_threshold=self.warning_threshold,
        )

    def resolution_status(self, ticket: Ticket, now: datetime) -> SlaStatus:
        policy = self.policy_for(ticket.priority)
        return evaluate_sla(
            self.calendar_for(ticket.priority),
            start=ticket.created_at,
            target_seconds=policy.resolution_minutes * 60,
            now=now,
            pauses=self.pauses_of(ticket),
            stopped_at=ticket.resolved_at,
            warning_threshold=self.warning_threshold,
        )

    def evaluate(self, ticket: Ticket, now: datetime) -> TicketSla:
        return TicketSla(self.response_status(ticket, now), self.resolution_status(ticket, now))

    def refresh_due_dates(self, ticket: Ticket, now: datetime) -> TicketSla:
        status = self.evaluate(ticket, now)
        ticket.response_due_at = status.response.due_at
        ticket.resolution_due_at = status.resolution.due_at
        return status
