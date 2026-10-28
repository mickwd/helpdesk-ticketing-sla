"""Máquina de estados del ticket. Las transiciones se validan en la capa de servicio."""

from __future__ import annotations

from app.domain.enums import TicketStatus as S


class InvalidTransition(ValueError):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"Transición no permitida: {current.value} → {target.value}")
        self.current = current
        self.target = target


ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.NUEVO: frozenset({S.ASIGNADO}),
    S.ASIGNADO: frozenset({S.EN_PROGRESO, S.EN_ESPERA_USUARIO, S.RESUELTO}),
    S.EN_PROGRESO: frozenset({S.ASIGNADO, S.EN_ESPERA_USUARIO, S.RESUELTO}),
    S.EN_ESPERA_USUARIO: frozenset({S.EN_PROGRESO, S.RESUELTO}),
    # Reapertura: resuelto vuelve a en_progreso si el usuario rechaza la solución
    S.RESUELTO: frozenset({S.CERRADO, S.EN_PROGRESO}),
    S.CERRADO: frozenset(),
}

# Estados en los que el reloj de SLA está detenido
PAUSED_STATUSES = frozenset({S.EN_ESPERA_USUARIO})

# Estados desde los que se puede escalar o desescalar
ESCALABLE_STATUSES = frozenset({S.NUEVO, S.ASIGNADO, S.EN_PROGRESO, S.EN_ESPERA_USUARIO})


def can_transition(current: S | str, target: S | str) -> bool:
    return S(target) in ALLOWED_TRANSITIONS[S(current)]


def validate_transition(current: S | str, target: S | str) -> None:
    current, target = S(current), S(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(current, target)


def is_escalable(status: S | str) -> bool:
    return S(status) in ESCALABLE_STATUSES
