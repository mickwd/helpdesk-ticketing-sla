"""Métricas operativas de la mesa de ayuda.

Definiciones (ver README):
- MTTA: promedio de minutos entre la creación y la primera respuesta.
- MTTR: promedio de horas entre la creación y la resolución.
- Cumplimiento de SLA: % de tickets resueltos dentro del objetivo de resolución
  (y % de primeras respuestas dentro del objetivo de respuesta).
- FCR (resolución en primer contacto): % de tickets resueltos en N1 sin escalar.
- Tasa de escalamiento: % de tickets que fueron escalados al menos una vez.
- Backlog: tickets abiertos por nivel y prioridad.

MTTA/MTTR se miden en tiempo calendario (lo que percibe el usuario); el
cumplimiento de SLA usa el calendario hábil de cada política.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DONE_STATUSES, OPEN_STATUSES, Level, Priority
from app.models import Ticket


def _pct(part: int, total: int) -> float | None:
    return round(100.0 * part / total, 1) if total else None


def _avg(values: Iterable[float], ndigits: int = 1) -> float | None:
    values = list(values)
    return round(mean(values), ndigits) if values else None


def _minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60


def load_tickets(
    session: Session, date_from: datetime | None = None, date_to: datetime | None = None
) -> list[Ticket]:
    query = select(Ticket)
    if date_from is not None:
        query = query.where(Ticket.created_at >= date_from)
    if date_to is not None:
        query = query.where(Ticket.created_at < date_to)
    return list(session.scalars(query).unique().all())


def mtta_minutes(tickets: list[Ticket]) -> float | None:
    return _avg(
        _minutes(t.first_responded_at - t.created_at) for t in tickets if t.first_responded_at
    )


def mttr_hours(tickets: list[Ticket]) -> float | None:
    return _avg(
        (t.resolved_at - t.created_at).total_seconds() / 3600 for t in tickets if t.resolved_at
    )


def resolved(tickets: list[Ticket]) -> list[Ticket]:
    return [t for t in tickets if t.status in DONE_STATUSES and t.resolved_at is not None]


def sla_compliance(tickets: list[Ticket]) -> dict[str, float | int | None]:
    done = resolved(tickets)
    responded = [t for t in tickets if t.first_responded_at is not None]
    met = sum(1 for t in done if not t.resolution_breached)
    response_met = sum(1 for t in responded if not t.response_breached)
    return {
        "resolved": len(done),
        "resolution_met": met,
        "resolution_pct": _pct(met, len(done)),
        "responded": len(responded),
        "response_met": response_met,
        "response_pct": _pct(response_met, len(responded)),
    }


def compliance_by(
    tickets: list[Ticket], key: Callable[[Ticket], str | None]
) -> list[dict[str, object]]:
    groups: dict[str, list[Ticket]] = defaultdict(list)
    for ticket in resolved(tickets):
        group = key(ticket)
        if group is not None:
            groups[group].append(ticket)
    rows = []
    for group, items in sorted(groups.items()):
        met = sum(1 for t in items if not t.resolution_breached)
        rows.append(
            {
                "key": group,
                "resolved": len(items),
                "met": met,
                "compliance_pct": _pct(met, len(items)),
                "mttr_hours": mttr_hours(items),
            }
        )
    return rows


def first_contact_resolution_rate(tickets: list[Ticket]) -> float | None:
    done = resolved(tickets)
    fcr = sum(1 for t in done if t.escalation_count == 0 and t.resolved_level == Level.N1)
    return _pct(fcr, len(done))


def escalation_rate(tickets: list[Ticket]) -> float | None:
    return _pct(sum(1 for t in tickets if t.escalation_count > 0), len(tickets))


def backlog(tickets: list[Ticket], now: datetime) -> dict[str, object]:
    open_tickets = [t for t in tickets if t.status in OPEN_STATUSES]
    by_level = Counter(t.level.value for t in open_tickets)
    by_priority = Counter(t.priority.value for t in open_tickets)
    by_status = Counter(t.status.value for t in open_tickets)
    overdue = sum(
        1 for t in open_tickets if t.resolution_due_at is not None and t.resolution_due_at < now
    )
    return {
        "total": len(open_tickets),
        "by_level": {lvl.value: by_level.get(lvl.value, 0) for lvl in Level},
        "by_priority": {p.value: by_priority.get(p.value, 0) for p in Priority},
        "by_status": dict(sorted(by_status.items())),
        "overdue": overdue,
        "unassigned": sum(1 for t in open_tickets if t.assignee_id is None),
    }


def weekly_volume(tickets: list[Ticket]) -> list[dict[str, object]]:
    created: Counter[str] = Counter()
    solved: Counter[str] = Counter()
    for t in tickets:
        week = (t.created_at - timedelta(days=t.created_at.weekday())).date().isoformat()
        created[week] += 1
        if t.resolved_at:
            rweek = (t.resolved_at - timedelta(days=t.resolved_at.weekday())).date().isoformat()
            solved[rweek] += 1
    weeks = sorted(set(created) | set(solved))
    return [{"week": w, "created": created.get(w, 0), "resolved": solved.get(w, 0)} for w in weeks]


def overview(
    session: Session,
    now: datetime,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, object]:
    tickets = load_tickets(session, date_from, date_to)
    return {
        "generated_at": now,
        "total_tickets": len(tickets),
        "mtta_minutes": mtta_minutes(tickets),
        "mttr_hours": mttr_hours(tickets),
        "sla": sla_compliance(tickets),
        "first_contact_resolution_pct": first_contact_resolution_rate(tickets),
        "escalation_rate_pct": escalation_rate(tickets),
        "backlog": backlog(tickets, now),
        "compliance_by_priority": compliance_by(tickets, lambda t: t.priority.value),
        "compliance_by_level": compliance_by(
            tickets, lambda t: t.resolved_level.value if t.resolved_level else None
        ),
        "compliance_by_agent": compliance_by(
            tickets, lambda t: t.resolved_by.full_name if t.resolved_by else None
        ),
        "by_category": dict(Counter(t.category.value for t in tickets).most_common()),
        "weekly_volume": weekly_volume(tickets),
    }
