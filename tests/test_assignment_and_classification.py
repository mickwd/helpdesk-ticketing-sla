"""Asignación por menor carga/especialidad y clasificación automática."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.enums import Category, Level, Role, Specialty, TicketStatus
from app.services.assignment import open_load, pick_agent
from app.services.classification import (
    MlClassifier,
    TicketClassifier,
    classify_with_rules,
    normalize_text,
    parse_rules,
)

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ asignación
class TestAssignment:
    def test_prefers_specialist(self, session, make_user):
        make_user(Role.AGENTE_N1, ["windows"])
        networker = make_user(Role.AGENTE_N1, ["redes"])
        choice = pick_agent(session, Level.N1, Specialty.REDES)
        assert choice.agent.id == networker.id
        assert choice.specialty_match

    def test_falls_back_to_any_agent_of_level(self, session, make_user):
        agent = make_user(Role.AGENTE_N2, ["windows"])
        make_user(Role.AGENTE_N1, ["linux"])  # otro nivel: no se considera
        choice = pick_agent(session, Level.N2, Specialty.LINUX)
        assert choice.agent.id == agent.id
        assert not choice.specialty_match

    def test_least_loaded_wins(self, session, make_user, create_ticket, team):
        # team trae n2_red como único especialista N2 en redes
        extra = make_user(Role.AGENTE_N2, ["redes"])
        for _ in range(2):
            create_ticket(title="No resuelve DNS interno", description="nslookup da timeout")
        load = open_load(session, [team["n2_red"].id, extra.id])
        assert sorted(load.values()) == [1, 1]  # se repartieron, no fueron al mismo agente

    def test_round_robin_on_tie(self, session, make_user, clock):
        first = make_user(Role.AGENTE_N1, ["redes"])
        second = make_user(Role.AGENTE_N1, ["redes"])
        first.last_assigned_at = clock.now()
        second.last_assigned_at = clock.now() - timedelta(hours=1)
        session.commit()
        assert pick_agent(session, Level.N1, Specialty.REDES).agent.id == second.id

    def test_resolved_tickets_do_not_count_as_load(
        self, session, service, create_ticket, team, make_user
    ):
        ticket = create_ticket()
        assert ticket.assignee_id == team["n1_red"].id
        service.transition(ticket, team["n1_red"], TicketStatus.RESUELTO, resolution="Se reinstaló")
        assert open_load(session, [team["n1_red"].id])[team["n1_red"].id] == 0

    def test_inactive_and_excluded_agents_are_skipped(self, session, make_user):
        make_user(Role.AGENTE_N3, ["redes"], active=False)
        busy = make_user(Role.AGENTE_N3, ["redes"])
        free = make_user(Role.AGENTE_N3, ["linux"])
        choice = pick_agent(session, Level.N3, Specialty.REDES, exclude_ids=[busy.id])
        assert choice.agent.id == free.id

    def test_no_agents(self, session):
        assert pick_agent(session, Level.N3, Specialty.REDES) is None


# ---------------------------------------------------------------- clasificación
@pytest.fixture
def rules(settings):
    from app.services.classification import load_rules

    return load_rules(settings.classification_rules_path)


class TestRules:
    @pytest.mark.parametrize(
        ("title", "description", "category", "specialty", "level", "rule"),
        [
            ("La VPN no conecta", "FortiClient da error", "red_conectividad", "redes", "N1", "vpn"),
            (
                "No resuelve nombres",
                "El DNS de la sucursal no responde",
                "red_conectividad",
                "redes",
                "N2",
                "dns_dhcp",
            ),
            (
                "Usuario bloqueado",
                "Olvidé la contraseña",
                "acceso_cuentas",
                "windows",
                "N1",
                "reset_contrasena",
            ),
            (
                "Base de datos lenta",
                "Postgres con deadlock",
                "base_de_datos",
                "bases_de_datos",
                "N2",
                "base_de_datos",
            ),
            (
                "Disco lleno en servidor",
                "Ubuntu sin espacio en /var",
                "servidores",
                "linux",
                "N2",
                "servidor_linux",
            ),
            ("La impresora no imprime", "Cola trabada", "impresion", "windows", "N1", "impresion"),
        ],
    )
    def test_keyword_rules(self, rules, title, description, category, specialty, level, rule):
        result = classify_with_rules(rules, title, description)
        assert result is not None
        assert (result.category, result.specialty, result.level, result.rule) == (
            Category(category),
            Specialty(specialty),
            Level(level),
            rule,
        )
        assert result.source == "reglas"

    def test_accents_and_case_are_ignored(self, rules):
        result = classify_with_rules(rules, "CONTRASEÑA VENCIDA", "")
        assert result.rule == "reset_contrasena"
        assert normalize_text("Contraseña ÁÉÍ") == "contrasena aei"

    def test_title_weighs_double(self, rules):
        # VPN en el título (2 pts) gana a correo en la descripción (1 pt)
        result = classify_with_rules(rules, "Problema con la VPN", "no llega el correo")
        assert result.rule == "vpn"
        assert result.score == 2

    def test_no_match_returns_none(self, rules):
        assert classify_with_rules(rules, "Consulta general", "Tengo una duda") is None

    def test_classifier_falls_back_to_default(self, rules):
        result = TicketClassifier(rules).classify("Consulta general", "Tengo una duda")
        assert result.source == "default"
        assert result.category == Category.OTRO
        assert result.level == Level.N1

    def test_tie_goes_to_first_rule(self):
        rules = parse_rules(
            {
                "rules": [
                    {"name": "a", "patterns": ["x"], "category": "otro", "specialty": "redes"},
                    {"name": "b", "patterns": ["x"], "category": "otro", "specialty": "linux"},
                ]
            }
        )
        assert classify_with_rules(rules, "x", "").rule == "a"


class TestMlClassifier:
    def test_missing_csv_disables_model(self, tmp_path):
        assert not MlClassifier(tmp_path / "no-existe.csv").available

    def test_model_is_used_when_rules_do_not_match(self, rules):
        pytest.importorskip("sklearn")
        ml = MlClassifier(ROOT / "data" / "sample_tickets.csv", min_confidence=0.0)
        assert ml.available
        result = TicketClassifier(rules, ml).classify(
            "La computadora hace pitidos", "No arranca y no da imagen en el monitor de la pc"
        )
        assert result.source in {"reglas", "modelo"}
        # sin palabras clave de reglas, decide el modelo
        result = TicketClassifier(rules, ml).classify(
            "Pitidos al prender", "La computadora hace tres pitidos y no da imagen"
        )
        assert result.source == "modelo"
        assert result.category == Category.HARDWARE
