"""Asignación automática: menor carga por especialidad con desempate round-robin."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import LEVEL_ROLE, OPEN_STATUSES, Level, Specialty
from app.models import Ticket, User

_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class AssignmentChoice:
    agent: User
    load: int
    specialty_match: bool


def open_load(session: Session, agent_ids: Iterable[int]) -> dict[int, int]:
    """Cantidad de tickets abiertos por agente."""
    ids = list(agent_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(Ticket.assignee_id, func.count(Ticket.id))
        .where(Ticket.assignee_id.in_(ids), Ticket.status.in_(list(OPEN_STATUSES)))
        .group_by(Ticket.assignee_id)
    ).all()
    load = dict.fromkeys(ids, 0)
    load.update(dict(rows))  # type: ignore[arg-type]
    return load


def agents_for_level(session: Session, level: Level) -> list[User]:
    return list(
        session.scalars(
            select(User)
            .where(User.role == LEVEL_ROLE[level], User.is_active.is_(True))
            .order_by(User.id)
        ).all()
    )


def pick_agent(
    session: Session,
    level: Level,
    specialty: Specialty,
    exclude_ids: Iterable[int] = (),
) -> AssignmentChoice | None:
    """Elige el agente del nivel con menos tickets abiertos.

    1. Se prefieren agentes con la especialidad del ticket; si no hay ninguno
       se usa cualquier agente activo del nivel.
    2. Ante igual carga, gana quien hace más tiempo que no recibe un ticket
       (round-robin), y luego el id más bajo para que sea determinístico.
    """
    excluded = set(exclude_ids)
    agents = [a for a in agents_for_level(session, level) if a.id not in excluded]
    if not agents:
        return None
    specialists = [a for a in agents if specialty in a.specialties]
    candidates = specialists or agents
    load = open_load(session, (a.id for a in candidates))
    chosen = min(
        candidates,
        key=lambda a: (load[a.id], a.last_assigned_at or _NEVER, a.id),
    )
    return AssignmentChoice(agent=chosen, load=load[chosen.id], specialty_match=bool(specialists))
