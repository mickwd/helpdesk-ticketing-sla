"""Job de SLA con reloj congelado: advertencias, incumplimientos y escalamiento."""

from __future__ import annotations

import pytest

from app.domain.enums import EventType, Level, NotificationKind, TicketStatus
from app.domain.sla import SlaState
from app.models import Notification
from app.scheduler import run_sla_job
from app.services.escalation import SlaMonitor
from tests.conftest import art

S = TicketStatus


@pytest.fixture
def monitor(service) -> SlaMonitor:
    return SlaMonitor(service)


def sla_events(ticket, event_type):
    return [e.to_value for e in ticket.events if e.event_type == event_type]


def test_response_warning_at_75_percent_only_once(monitor, create_ticket, clock, team, session):
    ticket = create_ticket()  # P3: 4h hábiles para responder
    clock.set(art(2026, 3, 11, 12, 59))
    assert monitor.run().warnings == []
    clock.set(art(2026, 3, 11, 13, 0))
    report = monitor.run()
    assert report.warnings == [ticket.id]
    assert sla_events(ticket, EventType.SLA_ADVERTENCIA) == ["respuesta"]
    note = session.query(Notification).filter_by(kind=NotificationKind.SLA_ADVERTENCIA).one()
    assert note.recipient_id == team["n1_red"].id
    clock.advance(minutes=30)
    assert monitor.run().warnings == []


def test_response_breach_escalates_to_n2_specialist(monitor, create_ticket, clock, team):
    ticket = create_ticket()
    clock.set(art(2026, 3, 11, 14, 1))
    report = monitor.run()
    assert report.breaches == [ticket.id]
    assert report.escalated == [ticket.id]
    assert ticket.level == Level.N2
    assert ticket.assignee_id == team["n2_red"].id
    assert ticket.response_breached
    escalation = next(e for e in ticket.events if e.event_type == EventType.ESCALAMIENTO)
    assert escalation.data == {"automatico": True}
    assert escalation.actor_id is None
    # Corridas siguientes no vuelven a escalar por el mismo incumplimiento
    clock.advance(minutes=5)
    assert monitor.run().escalated == []
    assert ticket.escalation_count == 1


def test_weekend_does_not_consume_sla(monitor, create_ticket, clock, service, team):
    ticket = create_ticket()
    service.transition(ticket, team["n1_red"], S.EN_PROGRESO)
    # Viernes 18:00 → 26h consumidas de 27; todo el fin de semana sigue igual
    clock.set(art(2026, 3, 15, 23, 0))
    report = monitor.run()
    assert report.breaches == []
    assert report.warnings == [ticket.id]


def test_resolution_breach_escalates(monitor, create_ticket, clock, service, team):
    ticket = create_ticket()
    clock.set(art(2026, 3, 11, 10, 30))
    service.transition(ticket, team["n1_red"], S.EN_PROGRESO)
    clock.set(art(2026, 3, 13, 16, 30))  # 24,5h de 27 = 90%
    assert monitor.run().warnings == [ticket.id]
    assert sla_events(ticket, EventType.SLA_ADVERTENCIA) == ["resolución"]
    clock.set(art(2026, 3, 16, 10, 1))
    report = monitor.run()
    assert report.escalated == [ticket.id]
    assert ticket.resolution_breached
    assert ticket.level == Level.N2
    assert sla_events(ticket, EventType.SLA_INCUMPLIDO) == ["resolución"]


def test_paused_ticket_never_breaches(monitor, create_ticket, clock, service, team):
    ticket = create_ticket()
    service.transition(ticket, team["n1_red"], S.EN_PROGRESO)
    service.transition(ticket, team["n1_red"], S.EN_ESPERA_USUARIO)
    clock.set(art(2026, 3, 25, 17))  # dos semanas después
    report = monitor.run()
    assert report.breaches == [] and report.warnings == []
    assert service.sla.resolution_status(ticket, clock.now()).state == SlaState.PAUSADO


def test_n3_breach_alerts_supervisor_instead_of_escalating(
    monitor, create_ticket, clock, service, team, session
):
    ticket = create_ticket()
    service.transition(ticket, team["n1_red"], S.EN_PROGRESO)
    service.escalate(ticket, team["n1_red"], "Requiere revisar el concentrador")
    service.escalate(ticket, team["n2_red"], "Requiere análisis del proveedor")
    clock.set(art(2026, 3, 16, 10, 1))
    report = monitor.run()
    assert report.escalated == []
    assert report.supervisor_alerts == [ticket.id]
    alert = session.query(Notification).filter_by(kind=NotificationKind.SLA_INCUMPLIDO).all()
    assert team["supervisor"].id in {n.recipient_id for n in alert}


def test_only_one_automatic_escalation_per_run(monitor, create_ticket, clock):
    ticket = create_ticket(impact="alto", urgency="alta")  # P1 24x7: 15 min / 4 h
    clock.advance(hours=5)
    report = monitor.run()
    assert ticket.response_breached and ticket.resolution_breached
    assert report.escalated == [ticket.id]
    assert ticket.level == Level.N2
    assert report.supervisor_alerts == [ticket.id]  # la 2da violación avisa a supervisión


def test_warning_without_assignee_goes_to_level_agents(monitor, service, make_user, clock, session):
    requester = make_user("solicitante")
    ticket, _ = service.create_ticket(
        requester, title="VPN caída", description="no conecta", impact="bajo", urgency="baja"
    )
    a1 = make_user("agente_n1", ["redes"])
    a2 = make_user("agente_n1", ["windows"])
    clock.set(art(2026, 3, 11, 16))  # P4: 8h de respuesta, 75% = 6h hábiles
    monitor.run()
    note_recipients = {
        n.recipient_id
        for n in session.query(Notification).filter_by(kind=NotificationKind.SLA_ADVERTENCIA)
    }
    assert note_recipients == {a1.id, a2.id}
    assert ticket.assignee_id is None


def test_resolved_tickets_are_ignored(monitor, create_ticket, clock, service, team):
    ticket = create_ticket()
    service.transition(ticket, team["n1_red"], S.RESUELTO, resolution="Reinstalación del cliente")
    clock.set(art(2026, 4, 30, 10))
    assert monitor.run().checked == 0


def test_scheduler_job_uses_its_own_session(app, create_ticket, clock, session):
    ticket = create_ticket()
    clock.set(art(2026, 3, 11, 14, 1))
    report = run_sla_job(app)
    assert report is not None
    assert report.escalated == [ticket.id]
    session.expire_all()
    assert session.get(type(ticket), ticket.id).level == Level.N2
