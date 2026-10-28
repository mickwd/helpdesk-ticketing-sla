"""Casos de uso de tickets: alta, transiciones, pausas, escalamiento y auditoría."""

from __future__ import annotations

import pytest

from app.domain.enums import (
    EventType,
    Level,
    NotificationKind,
    Priority,
    Role,
    TicketStatus,
)
from app.domain.state_machine import InvalidTransition
from app.models import Notification
from app.services.errors import ConflictError, PermissionDeniedError, ValidationError
from tests.conftest import art

S = TicketStatus


def event_types(ticket):
    return [e.event_type for e in ticket.events]


class TestCreate:
    def test_priority_classification_and_auto_assignment(self, create_ticket, team):
        ticket = create_ticket(impact="alto", urgency="media")
        assert ticket.priority == Priority.P2
        assert ticket.specialty.value == "redes"
        assert ticket.level == Level.N1
        assert ticket.status == S.ASIGNADO
        assert ticket.assignee_id == team["n1_red"].id
        assert ticket.classification_source == "reglas"
        assert ticket.classification_rule == "vpn"
        assert event_types(ticket)[:4] == [
            EventType.CREADO,
            EventType.CLASIFICADO,
            EventType.ASIGNACION,
            EventType.ESTADO,
        ]

    def test_due_dates_use_business_hours(self, create_ticket):
        # P3: 4h hábiles de respuesta, 27h de resolución, creado miércoles 10:00
        ticket = create_ticket()
        assert ticket.response_due_at == art(2026, 3, 11, 14)
        assert ticket.resolution_due_at == art(2026, 3, 16, 10)

    def test_explicit_category_wins_over_suggestion(self, create_ticket):
        ticket = create_ticket(category="hardware", specialty="windows")
        assert ticket.category.value == "hardware"
        assert ticket.classification_source == "manual"

    def test_rule_can_route_directly_to_n2(self, create_ticket, team):
        ticket = create_ticket(title="No resuelve DNS", description="nslookup falla")
        assert ticket.level == Level.N2
        assert ticket.assignee_id == team["n2_red"].id

    def test_without_agents_ticket_stays_new(self, service, make_user):
        requester = make_user(Role.SOLICITANTE)
        ticket, _ = service.create_ticket(
            requester,
            title="VPN caída",
            description="no conecta nada",
            impact="bajo",
            urgency="baja",
        )
        assert ticket.status == S.NUEVO
        assert ticket.assignee_id is None

    def test_p1_notifies_supervisor_immediately(self, create_ticket, team, session, channel):
        ticket = create_ticket(impact="alto", urgency="alta")
        assert ticket.priority == Priority.P1
        notes = session.query(Notification).filter_by(kind=NotificationKind.P1_CRITICO).all()
        assert [n.recipient_id for n in notes] == [team["supervisor"].id]
        assert any(m.kind == NotificationKind.P1_CRITICO for m in channel.sent)


class TestTransitions:
    def test_full_lifecycle_with_audit(self, service, create_ticket, team, clock):
        ticket = create_ticket()
        agent = team["n1_red"]
        clock.advance(minutes=20)
        service.transition(ticket, agent, S.EN_PROGRESO)
        assert ticket.first_responded_at == clock.now()
        clock.advance(hours=1)
        service.transition(ticket, agent, S.RESUELTO, resolution="Se reinstaló el cliente VPN")
        assert ticket.resolved_at == clock.now()
        assert ticket.resolved_level == Level.N1
        assert ticket.resolved_by_id == agent.id
        assert not ticket.resolution_breached
        service.transition(ticket, team["ana"], S.CERRADO)
        assert ticket.closed_at is not None
        statuses = [
            (e.from_value, e.to_value) for e in ticket.events if e.event_type == EventType.ESTADO
        ]
        assert statuses == [
            ("nuevo", "asignado"),
            ("asignado", "en_progreso"),
            ("en_progreso", "resuelto"),
            ("resuelto", "cerrado"),
        ]

    def test_invalid_transition_is_rejected(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(InvalidTransition):
            service.transition(ticket, team["n1_red"], S.CERRADO)

    def test_resolution_text_is_mandatory(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(ValidationError):
            service.transition(ticket, team["n1_red"], S.RESUELTO, resolution="ok")

    def test_requester_can_only_close_or_reopen(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(PermissionDeniedError):
            service.transition(ticket, team["ana"], S.EN_PROGRESO)
        service.transition(ticket, team["n1_red"], S.RESUELTO, resolution="Reinstalación completa")
        with pytest.raises(PermissionDeniedError):
            service.transition(ticket, team["jorge"], S.CERRADO)  # no es su ticket
        service.transition(ticket, team["ana"], S.EN_PROGRESO, note="Sigue fallando")
        assert ticket.status == S.EN_PROGRESO
        assert ticket.resolved_at is None

    def test_agent_of_other_level_cannot_operate(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(PermissionDeniedError):
            service.transition(ticket, team["n2_red"], S.EN_PROGRESO)

    def test_waiting_for_user_pauses_and_reply_resumes(self, service, create_ticket, team, clock):
        ticket = create_ticket()
        agent, ana = team["n1_red"], team["ana"]
        service.transition(ticket, agent, S.EN_PROGRESO)
        clock.advance(hours=1)
        service.add_comment(ticket, agent, "¿Desde qué red te conectás?", internal=False)
        service.transition(ticket, agent, S.EN_ESPERA_USUARIO)
        assert ticket.resolution_due_at is None  # pausado: vencimiento desconocido
        assert len(ticket.pauses) == 1
        clock.advance(hours=3)
        service.add_comment(ticket, ana, "Desde casa, con wifi", internal=False)
        assert ticket.status == S.EN_PROGRESO
        assert ticket.pauses[0].ended_at == clock.now()
        # El vencimiento se corrió exactamente las 3h hábiles de la pausa
        assert ticket.resolution_due_at == art(2026, 3, 16, 13)

    def test_first_response_from_public_comment_only(self, service, create_ticket, team):
        ticket = create_ticket()
        service.add_comment(ticket, team["n1_red"], "Nota para el equipo", internal=True)
        assert ticket.first_responded_at is None
        service.add_comment(ticket, team["n1_red"], "Hola, ya lo estamos viendo", internal=False)
        assert ticket.first_responded_at is not None

    def test_requester_cannot_add_internal_notes(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(PermissionDeniedError):
            service.add_comment(ticket, team["ana"], "secreto", internal=True)

    def test_update_priority_recalculates_sla(self, service, create_ticket, team):
        ticket = create_ticket()
        service.update_fields(ticket, team["n1_red"], impact="alto", urgency="alta")
        assert ticket.priority == Priority.P1
        assert EventType.PRIORIDAD in event_types(ticket)
        # P1 es 24x7 con 4h de resolución
        assert ticket.resolution_due_at == art(2026, 3, 11, 14)

    def test_attachment_metadata(self, service, create_ticket, team):
        ticket = create_ticket()
        attachment = service.add_attachment(
            ticket, team["ana"], filename="error.png", content_type="image/png", content=b"abc"
        )
        assert attachment.size_bytes == 3
        assert attachment.sha256.startswith("ba7816bf")
        assert EventType.ADJUNTO in event_types(ticket)


class TestEscalation:
    def test_manual_escalation_reassigns_by_specialty(self, service, create_ticket, team):
        ticket = create_ticket()
        service.escalate(ticket, team["n1_red"], "Requiere revisar el concentrador VPN")
        assert ticket.level == Level.N2
        assert ticket.assignee_id == team["n2_red"].id
        assert ticket.status == S.ASIGNADO
        assert ticket.escalation_count == 1
        event = next(e for e in ticket.events if e.event_type == EventType.ESCALAMIENTO)
        assert (event.from_value, event.to_value) == ("N1", "N2")
        assert event.message == "Requiere revisar el concentrador VPN"

    def test_reason_is_mandatory(self, service, create_ticket, team):
        ticket = create_ticket()
        with pytest.raises(ValidationError):
            service.escalate(ticket, team["n1_red"], "  corto ")

    def test_cannot_escalate_beyond_n3(self, service, create_ticket, team):
        ticket = create_ticket()
        service.escalate(ticket, team["n1_red"], "Necesita análisis de nivel 2")
        service.escalate(ticket, team["n2_red"], "Necesita análisis de nivel 3")
        assert ticket.level == Level.N3
        with pytest.raises(ConflictError):
            service.escalate(ticket, team["n3"], "No hay más niveles disponibles")

    def test_cannot_escalate_resolved(self, service, create_ticket, team):
        ticket = create_ticket()
        service.transition(ticket, team["n1_red"], S.RESUELTO, resolution="Se reinstaló todo")
        with pytest.raises(ConflictError):
            service.escalate(ticket, team["n1_red"], "Escalamiento tardío del caso")

    def test_deescalation_permissions(self, service, create_ticket, team):
        ticket = create_ticket()
        service.escalate(ticket, team["n1_red"], "Requiere revisar el concentrador")
        with pytest.raises(PermissionDeniedError):
            service.deescalate(ticket, team["n1_red"], "Vuelve a nivel uno por favor")
        service.deescalate(ticket, team["n2_red"], "Era un problema del cliente, lo sigue N1")
        assert ticket.level == Level.N1
        assert ticket.escalation_count == 1  # el desescalamiento no suma
        assert EventType.DESESCALAMIENTO in event_types(ticket)

    def test_escalation_from_waiting_closes_pause(self, service, create_ticket, team, clock):
        ticket = create_ticket()
        service.transition(ticket, team["n1_red"], S.EN_PROGRESO)
        service.transition(ticket, team["n1_red"], S.EN_ESPERA_USUARIO)
        clock.advance(hours=1)
        service.escalate(ticket, team["supervisor"], "Supervisión decide escalar el caso")
        assert ticket.pauses[-1].ended_at == clock.now()
        assert ticket.status == S.ASIGNADO

    def test_p1_escalation_notifies_supervisor(self, service, create_ticket, team, session):
        ticket = create_ticket(impact="alto", urgency="alta")
        service.escalate(ticket, team["n1_red"], "Caída general de la VPN corporativa")
        recipients = {
            n.recipient_id
            for n in session.query(Notification).filter_by(kind=NotificationKind.ESCALAMIENTO)
        }
        assert recipients == {team["n2_red"].id, team["supervisor"].id}
