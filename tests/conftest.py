"""Fixtures compartidas: base SQLite en memoria, reloj congelado y cliente HTTP."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import FrozenClock
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.domain.enums import Impact, Role, Specialty, Urgency
from app.main import create_app
from app.models import Ticket, User, UserSpecialty
from app.security import hash_password
from app.services.classification import TicketClassifier, load_rules
from app.services.notifications import MemoryChannel, Notifier
from app.services.sla_service import SlaEngine, load_sla_config
from app.services.tickets import TicketService

ROOT = Path(__file__).resolve().parent.parent
ART = ZoneInfo("America/Argentina/Buenos_Aires")
PASSWORD = "Secreta123"
_PASSWORD_HASH = hash_password(PASSWORD, iterations=1_000)


def art(*args: int) -> datetime:
    """Datetime en hora de Argentina."""
    return datetime(*args, tzinfo=ART)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        scheduler_enabled=False,
        ml_enabled=False,
        notifiers="",
        sla_config_path=ROOT / "config" / "sla.yaml",
        classification_rules_path=ROOT / "config" / "classification_rules.yaml",
        jwt_secret="secreto-de-tests-con-longitud-suficiente",
    )


@pytest.fixture
def clock() -> FrozenClock:
    # Miércoles 11/03/2026 10:00 ART, día hábil sin feriados cerca
    return FrozenClock(art(2026, 3, 11, 10, 0))


@pytest.fixture
def engine(settings: Settings):
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    factory = build_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture
def channel() -> MemoryChannel:
    return MemoryChannel()


@pytest.fixture
def notifier(channel: MemoryChannel) -> Notifier:
    return Notifier([channel])


@pytest.fixture
def sla_config(settings: Settings):
    return load_sla_config(settings.sla_config_path)


@pytest.fixture
def classifier(settings: Settings) -> TicketClassifier:
    return TicketClassifier(load_rules(settings.classification_rules_path))


@pytest.fixture
def service(session, clock, sla_config, notifier, classifier) -> TicketService:
    return TicketService(
        session=session,
        clock=clock,
        sla=SlaEngine(sla_config),
        notifier=notifier,
        classifier=classifier,
    )


@pytest.fixture
def make_user(session: Session, clock: FrozenClock) -> Callable[..., User]:
    counter = {"n": 0}

    def factory(
        role: Role | str,
        specialties: list[str] | None = None,
        email: str | None = None,
        active: bool = True,
    ) -> User:
        counter["n"] += 1
        role = Role(role)
        user = User(
            email=email or f"{role.value}.{counter['n']}@example.com",
            full_name=f"{role.value} {counter['n']}",
            password_hash=_PASSWORD_HASH,
            role=role,
            is_active=active,
            created_at=clock.now(),
        )
        user.specialty_links = [UserSpecialty(specialty=Specialty(s)) for s in specialties or []]
        session.add(user)
        session.commit()
        return user

    return factory


@pytest.fixture
def team(make_user) -> dict[str, User]:
    """Equipo mínimo: un agente por nivel/especialidad, supervisión y solicitantes."""
    return {
        "supervisor": make_user(Role.SUPERVISOR, email="supervisor@example.com"),
        "n1_win": make_user(
            Role.AGENTE_N1, ["windows", "aplicaciones"], email="n1.win@example.com"
        ),
        "n1_red": make_user(Role.AGENTE_N1, ["redes"], email="n1.red@example.com"),
        "n2_red": make_user(Role.AGENTE_N2, ["redes"], email="n2.red@example.com"),
        "n2_db": make_user(Role.AGENTE_N2, ["bases_de_datos", "linux"], email="n2.db@example.com"),
        "n3": make_user(Role.AGENTE_N3, ["redes", "bases_de_datos"], email="n3@example.com"),
        "ana": make_user(Role.SOLICITANTE, email="ana@example.com"),
        "jorge": make_user(Role.SOLICITANTE, email="jorge@example.com"),
    }


@pytest.fixture
def create_ticket(service: TicketService, team) -> Callable[..., Ticket]:
    def factory(
        title: str = "La VPN no conecta desde casa",
        description: str = "FortiClient queda trabado al 98% desde ayer",
        impact: str = "medio",
        urgency: str = "media",
        requester: User | None = None,
        **kwargs,
    ) -> Ticket:
        ticket, _ = service.create_ticket(
            requester or team["ana"],
            title=title,
            description=description,
            impact=Impact(impact),
            urgency=Urgency(urgency),
            **kwargs,
        )
        service.session.commit()
        return ticket

    return factory


@pytest.fixture
def app(settings, clock, engine, notifier):
    return create_app(settings, clock=clock, engine=engine, notifier=notifier)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth(client: TestClient) -> Callable[[str], dict[str, str]]:
    def login(email: str) -> dict[str, str]:
        response = client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return login
