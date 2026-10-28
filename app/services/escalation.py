"""Job periódico de SLA: advertencias al 75% y escalamiento automático al incumplir.

Reglas:
- Al llegar al umbral de advertencia (75% por defecto) de primera respuesta o de
  resolución se notifica al agente asignado (o al nivel si no hay asignado).
- Si se incumple la primera respuesta o la resolución, el ticket sube un nivel
  (N1 → N2 → N3) y se reasigna al agente de menor carga con la especialidad.
- Como máximo un escalamiento automático por ticket en cada corrida.
- Si el ticket ya está en N3 no se puede escalar: se avisa a supervisión.
- Los tickets P1 notifican siempre a supervisión.
- Los tickets en espera del usuario no consumen SLA (el reloj está pausado).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    LEVEL_ROLE,
    OPEN_STATUSES,
    EventType,
    NotificationKind,
    Priority,
)
from app.domain.sla import SlaStatus
from app.models import Ticket, User
from app.services.tickets import TicketService

logger = logging.getLogger("helpdesk.sla_job")


@dataclass
class SlaCheckReport:
    checked: int = 0
    warnings: list[int] = field(default_factory=list)
    breaches: list[int] = field(default_factory=list)
    escalated: list[int] = field(default_factory=list)
    supervisor_alerts: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "warnings": self.warnings,
            "breaches": self.breaches,
            "escalated": self.escalated,
            "supervisor_alerts": self.supervisor_alerts,
        }


class SlaMonitor:
    def __init__(self, service: TicketService) -> None:
        self.service = service

    @property
    def session(self) -> Session:
        return self.service.session

    def _level_agents(self, ticket: Ticket) -> list[User]:
        return list(
            self.session.scalars(
                select(User).where(User.role == LEVEL_ROLE[ticket.level], User.is_active.is_(True))
            ).all()
        )

    def _warning_recipients(self, ticket: Ticket) -> list[User]:
        recipients = [ticket.assignee] if ticket.assignee else self._level_agents(ticket)
        if ticket.priority == Priority.P1:
            recipients += self.service.supervisors()
        return recipients

    def _warn(self, ticket: Ticket, kind: str, status: SlaStatus, report: SlaCheckReport) -> None:
        now = self.service.now()
        due = f"{status.due_at:%d/%m %H:%M} UTC" if status.due_at else "pausado"
        self.service.record_event(
            ticket,
            EventType.SLA_ADVERTENCIA,
            None,
            to_value=kind,
            message=f"SLA de {kind} al {status.percent:.0%} (vence {due})",
        )
        self.service.notifier.notify(
            self.session,
            kind=NotificationKind.SLA_ADVERTENCIA,
            subject=f"#{ticket.id} SLA de {kind} al {status.percent:.0%}",
            body=f"{ticket.title} ({ticket.priority.value}, {ticket.level.value}). Vence {due}.",
            recipients=self._warning_recipients(ticket),
            ticket=ticket,
            now=now,
        )
        report.warnings.append(ticket.id)

    def _breach(
        self, ticket: Ticket, kind: str, status: SlaStatus, report: SlaCheckReport, escalated: bool
    ) -> bool:
        """Registra el incumplimiento y escala si corresponde. Devuelve True si escaló."""
        now = self.service.now()
        self.service.record_event(
            ticket,
            EventType.SLA_INCUMPLIDO,
            None,
            to_value=kind,
            message=f"SLA de {kind} incumplido ({status.percent:.0%} del objetivo)",
        )
        report.breaches.append(ticket.id)
        supervisors = self.service.supervisors()
        if not escalated and ticket.level.next() is not None:
            reason = f"Escalamiento automático por incumplimiento de SLA de {kind}"
            self.service.escalate(ticket, None, reason, automatic=True)
            report.escalated.append(ticket.id)
            return True
        # No se puede (o no corresponde) escalar: avisar a supervisión
        self.service.notifier.notify(
            self.session,
            kind=NotificationKind.SLA_INCUMPLIDO,
            subject=f"#{ticket.id} incumplió SLA de {kind} en {ticket.level.value}",
            body=f"{ticket.title} ({ticket.priority.value}). Requiere intervención de supervisión.",
            recipients=supervisors + ([ticket.assignee] if ticket.assignee else []),
            ticket=ticket,
            now=now,
        )
        report.supervisor_alerts.append(ticket.id)
        return False

    def run(self) -> SlaCheckReport:
        now = self.service.now()
        report = SlaCheckReport()
        tickets = self.session.scalars(
            select(Ticket).where(Ticket.status.in_(list(OPEN_STATUSES))).order_by(Ticket.id)
        ).all()
        for ticket in tickets:
            report.checked += 1
            sla = self.service.sla.evaluate(ticket, now)
            threshold = self.service.sla.warning_threshold
            escalated = False

            if ticket.first_responded_at is None:
                response = sla.response
                if response.breached and not ticket.response_breached:
                    ticket.response_breached = True
                    ticket.response_warning_sent = True
                    escalated = self._breach(ticket, "respuesta", response, report, escalated)
                elif (
                    not response.breached
                    and response.percent >= threshold
                    and not ticket.response_warning_sent
                ):
                    ticket.response_warning_sent = True
                    self._warn(ticket, "respuesta", response, report)

            resolution = sla.resolution
            if resolution.breached and not ticket.resolution_breached:
                ticket.resolution_breached = True
                ticket.resolution_warning_sent = True
                self._breach(ticket, "resolución", resolution, report, escalated)
            elif (
                not resolution.breached
                and resolution.percent >= threshold
                and not ticket.resolution_warning_sent
            ):
                ticket.resolution_warning_sent = True
                self._warn(ticket, "resolución", resolution, report)

            self.service.sla.refresh_due_dates(ticket, now)
        self.session.flush()
        if report.warnings or report.breaches:
            logger.info("Chequeo de SLA: %s", report.as_dict())
        return report
