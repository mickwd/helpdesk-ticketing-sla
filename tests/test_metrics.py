"""Métricas calculadas sobre un conjunto de tickets controlado."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.enums import Level, TicketStatus
from app.services import metrics
from tests.conftest import art

S = TicketStatus


@pytest.fixture
def scenario(service, create_ticket, team, clock):
    """Cuatro tickets con tiempos conocidos.

    1. N1 resuelto sin escalar: respuesta 10 min, resolución 2 h, dentro de SLA.
    2. Escalado a N2 y resuelto: respuesta 30 min, resolución 4 h.
    3. Resuelto fuera de SLA (P1 24x7, 6 h).
    4. Abierto en N1 sin respuesta.
    """
    start = clock.now()
    t1 = create_ticket()
    clock.advance(minutes=10)
    service.transition(t1, team["n1_red"], S.EN_PROGRESO)
    clock.set(start + timedelta(hours=2))
    service.transition(t1, team["n1_red"], S.RESUELTO, resolution="Reinstalación del cliente")

    clock.set(start)
    t2 = create_ticket(title="VPN lenta", description="Se corta seguido la VPN")
    clock.advance(minutes=30)
    service.transition(t2, team["n1_red"], S.EN_PROGRESO)
    service.escalate(t2, team["n1_red"], "Problema en el concentrador de VPN")
    service.transition(t2, team["n2_red"], S.EN_PROGRESO)
    clock.set(start + timedelta(hours=4))
    service.transition(t2, team["n2_red"], S.RESUELTO, resolution="Se ajustó el MTU del túnel")

    clock.set(start)
    t3 = create_ticket(title="VPN caída para todos", impact="alto", urgency="alta")
    clock.advance(minutes=5)
    service.transition(t3, team["n1_red"], S.EN_PROGRESO)
    clock.set(start + timedelta(hours=6))
    service.transition(t3, team["n1_red"], S.RESUELTO, resolution="Se reinició el firewall")

    clock.set(start)
    t4 = create_ticket(title="VPN no conecta", description="Error de certificado en VPN")
    service.session.commit()
    clock.set(start + timedelta(hours=7))
    return [t1, t2, t3, t4]


def test_mtta_and_mttr(scenario):
    assert metrics.mtta_minutes(scenario) == pytest.approx(15.0)  # (10 + 30 + 5) / 3
    assert metrics.mttr_hours(scenario) == pytest.approx(4.0)  # (2 + 4 + 6) / 3


def test_sla_compliance(scenario):
    result = metrics.sla_compliance(scenario)
    assert result["resolved"] == 3
    assert result["resolution_met"] == 2
    assert result["resolution_pct"] == pytest.approx(66.7)
    assert result["response_pct"] == 100.0


def test_compliance_by_priority_and_level(scenario):
    by_priority = {r["key"]: r for r in metrics.compliance_by(scenario, lambda t: t.priority.value)}
    assert by_priority["P1"]["compliance_pct"] == 0.0
    assert by_priority["P3"]["compliance_pct"] == 100.0
    by_level = {
        r["key"]: r["resolved"]
        for r in metrics.compliance_by(scenario, lambda t: t.resolved_level.value)
    }
    assert by_level == {"N1": 2, "N2": 1}


def test_fcr_and_escalation_rate(scenario):
    assert metrics.first_contact_resolution_rate(scenario) == pytest.approx(66.7)
    assert metrics.escalation_rate(scenario) == 25.0


def test_backlog(scenario, clock):
    backlog = metrics.backlog(scenario, clock.now())
    assert backlog["total"] == 1
    assert backlog["by_level"] == {"N1": 1, "N2": 0, "N3": 0}
    assert backlog["by_priority"]["P3"] == 1


def test_overview_with_date_filter(scenario, session, clock):
    data = metrics.overview(session, clock.now())
    assert data["total_tickets"] == 4
    assert data["weekly_volume"][0]["created"] == 4
    empty = metrics.overview(session, clock.now(), date_from=art(2026, 4, 1))
    assert empty["total_tickets"] == 0
    assert empty["mttr_hours"] is None
    assert empty["sla"]["resolution_pct"] is None


def test_resolved_level_is_recorded(scenario):
    assert [t.resolved_level for t in scenario[:3]] == [Level.N1, Level.N2, Level.N1]
