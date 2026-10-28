"""Flujos completos por HTTP (TestClient + SQLite en memoria) y permisos por rol."""

from __future__ import annotations

from datetime import timedelta

import jwt

from app.domain.enums import Role
from tests.conftest import art


def create(client, headers, **overrides):
    payload = {
        "title": "La VPN no conecta desde casa",
        "description": "FortiClient queda trabado en 98% desde ayer a la tarde",
        "impact": "medio",
        "urgency": "alta",
        **overrides,
    }
    response = client.post("/api/tickets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestAuth:
    def test_login_and_me(self, client, team, auth):
        headers = auth("n1.red@example.com")
        me = client.get("/api/auth/me", headers=headers).json()
        assert me["role"] == "agente_n1"
        assert me["specialties"] == ["redes"]

    def test_wrong_password(self, client, team):
        response = client.post(
            "/api/auth/login", data={"username": "ana@example.com", "password": "incorrecta"}
        )
        assert response.status_code == 401

    def test_requires_token(self, client):
        assert client.get("/api/tickets").status_code == 401

    def test_invalid_token(self, client):
        response = client.get("/api/tickets", headers={"Authorization": "Bearer basura"})
        assert response.status_code == 401

    def test_token_expires_with_injected_clock(self, client, team, auth, clock):
        headers = auth("ana@example.com")
        clock.advance(hours=9)  # vencimiento por defecto: 8 horas
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    def test_token_signed_with_other_secret(self, client, team, clock):
        token = jwt.encode(
            {"sub": str(team["supervisor"].id), "exp": clock.now() + timedelta(hours=1)},
            "otro-secreto-de-longitud-suficiente-xx",
            algorithm="HS256",
        )
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_inactive_user_cannot_login(self, client, make_user):
        user = make_user(Role.SOLICITANTE, active=False)
        response = client.post(
            "/api/auth/login", data={"username": user.email, "password": "Secreta123"}
        )
        assert response.status_code == 401


class TestEndToEnd:
    def test_full_ticket_flow(self, client, team, auth, clock):
        ana = auth("ana@example.com")
        agent = auth("n1.red@example.com")
        n2 = auth("n2.red@example.com")

        preview = client.post(
            "/api/classify",
            json={
                "title": "VPN no conecta",
                "description": "",
                "impact": "medio",
                "urgency": "alta",
            },
            headers=ana,
        ).json()
        assert preview["specialty"] == "redes"
        assert preview["priority"] == "P2"

        created = create(client, ana)
        ticket = created["ticket"]
        assert created["classification"]["rule"] == "vpn"
        assert ticket["priority"] == "P2"
        assert ticket["status"] == "asignado"
        assert ticket["assignee"]["email"] == "n1.red@example.com"
        assert ticket["sla_response"]["state"] == "en_curso"
        tid = ticket["id"]

        clock.advance(minutes=10)
        detail = client.post(
            f"/api/tickets/{tid}/transition", json={"status": "en_progreso"}, headers=agent
        ).json()
        assert detail["sla_response"]["state"] == "cumplido"

        client.post(
            f"/api/tickets/{tid}/comments",
            json={"body": "Logs del firewall adjuntos", "internal": True},
            headers=agent,
        )
        upload = client.post(
            f"/api/tickets/{tid}/attachments",
            files={"file": ("captura.png", b"\x89PNG fake", "image/png")},
            headers=ana,
        )
        assert upload.status_code == 201
        assert upload.json()["size_bytes"] == 9

        escalated = client.post(
            f"/api/tickets/{tid}/escalate",
            json={"reason": "Falla en el concentrador VPN, requiere N2"},
            headers=agent,
        ).json()
        assert escalated["level"] == "N2"
        assert escalated["assignee"]["email"] == "n2.red@example.com"

        # N1 ya no lo ve en su cola (salió de su nivel y no está asignado a él)
        assert client.get(f"/api/tickets/{tid}", headers=agent).status_code == 404

        client.post(f"/api/tickets/{tid}/transition", json={"status": "en_progreso"}, headers=n2)
        clock.advance(hours=2)
        resolved = client.post(
            f"/api/tickets/{tid}/transition",
            json={"status": "resuelto", "resolution": "Se reinició el servicio SSL-VPN"},
            headers=n2,
        ).json()
        assert resolved["status"] == "resuelto"
        assert resolved["sla_resolution"]["state"] == "cumplido"
        assert resolved["allowed_transitions"] == ["en_progreso", "cerrado"]

        mine = client.get(f"/api/tickets/{tid}", headers=ana).json()
        assert mine["allowed_transitions"] == ["en_progreso", "cerrado"]
        assert all(not c["is_internal"] for c in mine["comments"])
        assert all(e["event_type"] != "clasificado" for e in mine["events"])

        closed = client.post(
            f"/api/tickets/{tid}/transition", json={"status": "cerrado"}, headers=ana
        ).json()
        assert closed["status"] == "cerrado"

        events = client.get(f"/api/tickets/{tid}/events", headers=auth("supervisor@example.com"))
        types = [e["event_type"] for e in events.json()]
        for expected in ("creado", "asignacion", "escalamiento", "adjunto", "comentario"):
            assert expected in types

        notifications = client.get("/api/notifications", headers=ana).json()
        assert any("resuelto" in n["subject"] for n in notifications)
        read = client.post(f"/api/notifications/{notifications[0]['id']}/read", headers=ana)
        assert read.json()["is_read"] is True

    def test_invalid_transition_returns_409(self, client, team, auth):
        ana = auth("ana@example.com")
        tid = create(client, ana)["ticket"]["id"]
        response = client.post(
            f"/api/tickets/{tid}/transition",
            json={"status": "cerrado"},
            headers=auth("n1.red@example.com"),
        )
        assert response.status_code == 409
        assert "no permitida" in response.json()["detail"]

    def test_escalation_requires_reason(self, client, team, auth):
        tid = create(client, auth("ana@example.com"))["ticket"]["id"]
        response = client.post(
            f"/api/tickets/{tid}/escalate",
            json={"reason": "corto"},
            headers=auth("n1.red@example.com"),
        )
        assert response.status_code == 422

    def test_manual_assign_and_deescalate(self, client, team, auth, make_user):
        supervisor = auth("supervisor@example.com")
        other = make_user(Role.AGENTE_N1, ["windows"])
        tid = create(client, auth("ana@example.com"))["ticket"]["id"]
        assigned = client.post(
            f"/api/tickets/{tid}/assign", json={"assignee_id": other.id}, headers=supervisor
        ).json()
        assert assigned["assignee"]["id"] == other.id
        wrong_level = client.post(
            f"/api/tickets/{tid}/assign", json={"assignee_id": team["n3"].id}, headers=supervisor
        )
        assert wrong_level.status_code == 422
        client.post(
            f"/api/tickets/{tid}/escalate",
            json={"reason": "Decisión de supervisión"},
            headers=supervisor,
        )
        back = client.post(
            f"/api/tickets/{tid}/deescalate",
            json={"reason": "Se resuelve con el procedimiento estándar"},
            headers=supervisor,
        ).json()
        assert back["level"] == "N1"

    def test_patch_recomputes_priority(self, client, team, auth):
        tid = create(client, auth("ana@example.com"))["ticket"]["id"]
        response = client.patch(
            f"/api/tickets/{tid}",
            json={"impact": "alto", "urgency": "alta"},
            headers=auth("n1.red@example.com"),
        )
        assert response.json()["priority"] == "P1"


class TestVisibility:
    def test_requester_sees_only_own_tickets(self, client, team, auth):
        ana, jorge = auth("ana@example.com"), auth("jorge@example.com")
        tid = create(client, ana)["ticket"]["id"]
        create(client, jorge)
        assert client.get("/api/tickets", headers=ana).json()["total"] == 1
        assert client.get(f"/api/tickets/{tid}", headers=jorge).status_code == 404

    def test_agents_see_their_level_queue(self, client, team, auth):
        ana = auth("ana@example.com")
        create(client, ana)  # VPN -> N1
        create(client, ana, title="No resuelve DNS interno", description="nslookup falla siempre")
        n1 = client.get("/api/tickets", headers=auth("n1.win@example.com")).json()
        n2 = client.get("/api/tickets", headers=auth("n2.db@example.com")).json()
        supervisor = client.get("/api/tickets", headers=auth("supervisor@example.com")).json()
        assert [t["level"] for t in n1["items"]] == ["N1"]
        assert [t["level"] for t in n2["items"]] == ["N2"]
        assert supervisor["total"] == 2

    def test_filters(self, client, team, auth, clock):
        ana = auth("ana@example.com")
        create(client, ana, impact="alto", urgency="alta")
        create(
            client,
            ana,
            title="Impresora no imprime",
            description="La cola está trabada",
            impact="bajo",
            urgency="baja",
        )
        sup = auth("supervisor@example.com")
        p1 = client.get("/api/tickets?priority=P1", headers=sup).json()
        assert [t["priority"] for t in p1["items"]] == ["P1"]
        search = client.get("/api/tickets?q=impresora", headers=sup).json()
        assert search["total"] == 1
        clock.advance(hours=5)
        breached = client.get("/api/tickets?sla=incumplido", headers=sup).json()
        assert [t["priority"] for t in breached["items"]] == ["P1"]

    def test_requester_cannot_escalate_or_see_metrics(self, client, team, auth):
        ana = auth("ana@example.com")
        tid = create(client, ana)["ticket"]["id"]
        response = client.post(
            f"/api/tickets/{tid}/escalate", json={"reason": "Quiero que lo vea N2"}, headers=ana
        )
        assert response.status_code == 403
        assert client.get("/api/metrics/overview", headers=ana).status_code == 403
        assert client.get("/api/users", headers=ana).status_code == 403
        assert client.get("/api/users/agents", headers=ana).status_code == 403

    def test_only_supervisor_manages_users_and_sla(self, client, team, auth):
        agent = auth("n1.red@example.com")
        payload = {
            "email": "nuevo@example.com",
            "full_name": "Agente Nuevo",
            "password": "ClaveSegura1",
            "role": "agente_n1",
            "specialties": ["linux"],
        }
        assert client.post("/api/users", json=payload, headers=agent).status_code == 403
        sup = auth("supervisor@example.com")
        created = client.post("/api/users", json=payload, headers=sup)
        assert created.status_code == 201
        assert client.post("/api/users", json=payload, headers=sup).status_code == 409
        policy = {
            "first_response_minutes": 20,
            "resolution_minutes": 300,
            "business_hours_only": False,
        }
        assert client.put("/api/sla/policies/P2", json=policy, headers=agent).status_code == 403
        assert client.put("/api/sla/policies/P2", json=policy, headers=sup).status_code == 200
        policies = {p["priority"]: p for p in client.get("/api/sla/policies", headers=agent).json()}
        assert policies["P2"]["first_response_minutes"] == 20


class TestOperations:
    def test_sla_check_endpoint(self, client, team, auth, clock):
        tid = create(client, auth("ana@example.com"), impact="alto", urgency="alta")["ticket"]["id"]
        clock.set(art(2026, 3, 11, 10, 20))
        sup = auth("supervisor@example.com")
        report = client.post("/api/sla/check", headers=sup).json()
        assert report["escalated"] == [tid]
        assert client.post("/api/sla/check", headers=auth("n1.red@example.com")).status_code == 403

    def test_knowledge_base(self, client, team, auth):
        ana = auth("ana@example.com")
        agent = auth("n1.red@example.com")
        tid = create(client, ana)["ticket"]["id"]
        article = {
            "title": "VPN FortiClient: error al 98%",
            "body": "Reinstalar el cliente con el perfil corporativo actualizado.",
            "keywords": ["vpn", "forticlient"],
            "category": "red_conectividad",
            "specialty": "redes",
            "ticket_ids": [tid],
        }
        # el ticket todavía no está resuelto
        assert client.post("/api/kb/articles", json=article, headers=agent).status_code == 409
        client.post(
            f"/api/tickets/{tid}/transition",
            json={"status": "resuelto", "resolution": "Reinstalación del cliente VPN"},
            headers=agent,
        )
        created = client.post("/api/kb/articles", json=article, headers=agent)
        assert created.status_code == 201
        assert created.json()["ticket_ids"] == [tid]
        assert client.post("/api/kb/articles", json=article, headers=ana).status_code == 403

        suggestions = client.get("/api/kb/suggest?q=no anda la vpn", headers=ana).json()
        assert suggestions[0]["title"] == article["title"]
        assert "vpn" in suggestions[0]["matched"]

        new = create(client, ana, title="Error en VPN", description="FortiClient no conecta")
        assert new["classification"]["suggested_articles"][0]["id"] == created.json()["id"]
        detail = client.get(f"/api/tickets/{new['ticket']['id']}", headers=agent).json()
        assert detail["suggested_articles"]

    def test_metrics_endpoints(self, client, team, auth):
        ana = auth("ana@example.com")
        agent = auth("n1.red@example.com")
        tid = create(client, ana)["ticket"]["id"]
        client.post(
            f"/api/tickets/{tid}/transition",
            json={"status": "resuelto", "resolution": "Reinstalación del cliente VPN"},
            headers=agent,
        )
        overview = client.get("/api/metrics/overview", headers=agent).json()
        assert overview["total_tickets"] == 1
        assert overview["first_contact_resolution_pct"] == 100.0
        by_agent = client.get("/api/metrics/sla-compliance?group_by=agent", headers=agent).json()
        assert by_agent["groups"][0]["key"] == team["n1_red"].full_name
        assert (
            client.get("/api/metrics/sla-compliance?group_by=foo", headers=agent).status_code == 422
        )
        backlog = client.get("/api/metrics/backlog", headers=agent).json()
        assert backlog["total"] == 0

    def test_health_and_frontend(self, client):
        assert client.get("/health").json()["status"] == "ok"
        index = client.get("/")
        assert index.status_code == 200
        assert "Mesa de Ayuda" in index.text
        assert client.get("/static/app.js").status_code == 200
