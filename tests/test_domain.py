"""Matriz de prioridad ITIL y máquina de estados."""

from __future__ import annotations

import pytest

from app.domain.enums import Impact, Level, Priority, TicketStatus, Urgency
from app.domain.priority import compute_priority
from app.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    can_transition,
    is_escalable,
    validate_transition,
)

S = TicketStatus


@pytest.mark.parametrize(
    ("impact", "urgency", "expected"),
    [
        ("alto", "alta", "P1"),
        ("alto", "media", "P2"),
        ("alto", "baja", "P3"),
        ("medio", "alta", "P2"),
        ("medio", "media", "P3"),
        ("medio", "baja", "P4"),
        ("bajo", "alta", "P3"),
        ("bajo", "media", "P4"),
        ("bajo", "baja", "P4"),
    ],
)
def test_priority_matrix(impact, urgency, expected):
    assert compute_priority(Impact(impact), Urgency(urgency)) == Priority(expected)


def test_priority_matrix_rejects_unknown_values():
    with pytest.raises(ValueError):
        compute_priority("altisimo", "alta")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.NUEVO, S.ASIGNADO),
        (S.ASIGNADO, S.EN_PROGRESO),
        (S.ASIGNADO, S.RESUELTO),
        (S.EN_PROGRESO, S.EN_ESPERA_USUARIO),
        (S.EN_ESPERA_USUARIO, S.EN_PROGRESO),
        (S.EN_PROGRESO, S.RESUELTO),
        (S.RESUELTO, S.CERRADO),
        (S.RESUELTO, S.EN_PROGRESO),
    ],
)
def test_allowed_transitions(current, target):
    assert can_transition(current, target)
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.NUEVO, S.RESUELTO),
        (S.NUEVO, S.CERRADO),
        (S.ASIGNADO, S.CERRADO),
        (S.EN_ESPERA_USUARIO, S.CERRADO),
        (S.CERRADO, S.EN_PROGRESO),
        (S.CERRADO, S.NUEVO),
        (S.EN_PROGRESO, S.NUEVO),
    ],
)
def test_forbidden_transitions(current, target):
    assert not can_transition(current, target)
    with pytest.raises(InvalidTransition, match="no permitida"):
        validate_transition(current, target)


def test_closed_is_terminal_and_every_status_is_defined():
    assert ALLOWED_TRANSITIONS[S.CERRADO] == frozenset()
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_escalable_statuses():
    assert is_escalable(S.EN_ESPERA_USUARIO)
    assert not is_escalable(S.RESUELTO)
    assert not is_escalable(S.CERRADO)


def test_level_navigation():
    assert Level.N1.next() == Level.N2
    assert Level.N3.next() is None
    assert Level.N1.previous() is None
    assert Level.N3.previous() == Level.N2
    assert Level.N2.rank == 2
