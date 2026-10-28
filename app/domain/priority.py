"""Matriz impacto × urgencia estilo ITIL para calcular la prioridad."""

from __future__ import annotations

from app.domain.enums import Impact, Priority, Urgency

PRIORITY_MATRIX: dict[tuple[Impact, Urgency], Priority] = {
    (Impact.ALTO, Urgency.ALTA): Priority.P1,
    (Impact.ALTO, Urgency.MEDIA): Priority.P2,
    (Impact.ALTO, Urgency.BAJA): Priority.P3,
    (Impact.MEDIO, Urgency.ALTA): Priority.P2,
    (Impact.MEDIO, Urgency.MEDIA): Priority.P3,
    (Impact.MEDIO, Urgency.BAJA): Priority.P4,
    (Impact.BAJO, Urgency.ALTA): Priority.P3,
    (Impact.BAJO, Urgency.MEDIA): Priority.P4,
    (Impact.BAJO, Urgency.BAJA): Priority.P4,
}


def compute_priority(impact: Impact | str, urgency: Urgency | str) -> Priority:
    return PRIORITY_MATRIX[(Impact(impact), Urgency(urgency))]
