"""Reglas de visibilidad y permisos por rol."""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_

from app.domain.enums import AGENT_ROLES, ROLE_LEVEL, Level, Role
from app.models import Ticket, User


def is_agent(user: User) -> bool:
    return user.role in AGENT_ROLES


def is_staff(user: User) -> bool:
    return is_agent(user) or user.role == Role.SUPERVISOR


def agent_level(user: User) -> Level | None:
    return ROLE_LEVEL.get(user.role)


def visible_tickets_clause(user: User) -> ColumnElement[bool] | None:
    """Filtro SQL de los tickets que el usuario puede ver. None = todos."""
    if user.role == Role.SUPERVISOR:
        return None
    if user.role == Role.SOLICITANTE:
        return Ticket.requester_id == user.id
    level = agent_level(user)
    return or_(Ticket.level == level, Ticket.assignee_id == user.id)


def can_view_ticket(user: User, ticket: Ticket) -> bool:
    if user.role == Role.SUPERVISOR:
        return True
    if user.role == Role.SOLICITANTE:
        return ticket.requester_id == user.id
    return ticket.level == agent_level(user) or ticket.assignee_id == user.id


def can_work_ticket(user: User, ticket: Ticket) -> bool:
    """Puede cambiar estado, comentar internamente, escalar."""
    if user.role == Role.SUPERVISOR:
        return True
    if not is_agent(user):
        return False
    return ticket.level == agent_level(user) or ticket.assignee_id == user.id


def can_deescalate(user: User, ticket: Ticket) -> bool:
    if user.role == Role.SUPERVISOR:
        return True
    level = agent_level(user)
    return level is not None and level != Level.N1 and can_work_ticket(user, ticket)


def can_see_internal(user: User) -> bool:
    return is_staff(user)


def can_view_metrics(user: User) -> bool:
    return is_staff(user)
