"""Carga datos de demo: usuarios, políticas de SLA, artículos y ~200 tickets históricos.

Los tickets se generan pasando por la capa de servicio con un reloj simulado,
así cada uno tiene su auditoría completa (creación, asignación, escalamientos,
pausas, resolución y cierre) y las métricas del dashboard son coherentes.

Uso:
    python -m app.seed                # falla si ya hay datos
    python -m app.seed --reset        # borra todo y vuelve a cargar
    python -m app.seed --if-empty     # carga solo si la base está vacía (Docker)
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clock import FrozenClock, SystemClock
from app.config import Settings, get_settings
from app.db import Base, build_engine, build_session_factory
from app.domain.enums import Level, Role, Specialty, TicketStatus
from app.models import SlaPolicy, Ticket, User, UserSpecialty
from app.security import hash_password
from app.seed_data import DEMO_PASSWORD, DEMO_USERS, KB_ARTICLES, TICKET_TEMPLATES
from app.services import knowledge
from app.services.classification import build_classifier
from app.services.errors import ServiceError
from app.services.escalation import SlaMonitor
from app.services.notifications import Notifier
from app.services.sla_service import SlaEngine, load_sla_config
from app.services.tickets import TicketService

logger = logging.getLogger("helpdesk.seed")

ESCALATION_REASONS = [
    "Requiere acceso administrativo a la infraestructura que N1 no tiene",
    "Se descartó problema en el puesto del usuario, se sospecha falla de servidor",
    "Diagnóstico inicial completo, necesita análisis especializado",
    "El procedimiento estándar de la base de conocimiento no resolvió el problema",
    "Impacta a varios usuarios, se requiere intervención del nivel superior",
]
WAITING_QUESTIONS = [
    "¿Podés confirmar si el problema sigue ocurriendo después de reiniciar?",
    "Necesitamos una captura de pantalla del error para continuar.",
    "¿Desde qué equipo y red estás intentando conectarte?",
    "¿Nos confirmás un horario para conectarnos de forma remota?",
]
USER_REPLIES = [
    "Sí, sigue pasando. Adjunto la captura.",
    "Ya lo reinicié y el error persiste.",
    "Estoy en la oficina, conectado por cable.",
    "Pueden conectarse a las 15 hs.",
]


def _clear(session: Session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))
    session.commit()


def _business_time(rng: random.Random, day: datetime, tz: ZoneInfo) -> datetime:
    """Hora aleatoria dentro de la jornada (con algo de actividad fuera de horario)."""
    hour = rng.choices(range(7, 21), weights=[1, 3, 8, 9, 9, 7, 6, 8, 8, 7, 5, 3, 1, 1])[0]
    local = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=tz)
    return local.astimezone(UTC)


def _creation_times(rng: random.Random, now: datetime, total: int, tz: ZoneInfo, recent: int):
    days = []
    cursor = (now - timedelta(days=90)).astimezone(tz)
    while cursor.date() < now.astimezone(tz).date():
        if cursor.weekday() < 5 or rng.random() < 0.08:  # algún incidente de fin de semana
            days.append(cursor)
        cursor += timedelta(days=1)
    old_days = days[:-4]
    recent_days = [*days[-4:], now.astimezone(tz)]
    times = [_business_time(rng, rng.choice(old_days), tz) for _ in range(total - recent)]
    for _ in range(recent):
        t = _business_time(rng, rng.choice(recent_days), tz)
        times.append(min(t, now - timedelta(minutes=rng.randint(5, 240))))
    return sorted(times)


def _create_users(session: Session, now: datetime) -> dict[str, User]:
    users: dict[str, User] = {}
    password = hash_password(DEMO_PASSWORD)
    for email, name, role, specialties in DEMO_USERS:
        user = User(
            email=email,
            full_name=name,
            password_hash=password,
            role=Role(role),
            is_active=True,
            created_at=now - timedelta(days=120),
        )
        user.specialty_links = [UserSpecialty(specialty=Specialty(s)) for s in specialties]
        session.add(user)
        users[email] = user
    session.flush()
    return users


def _create_policies(session: Session, settings: Settings) -> None:
    config = load_sla_config(settings.sla_config_path)
    for policy in config.policies.values():
        session.add(
            SlaPolicy(
                priority=policy.priority,
                first_response_minutes=policy.first_response_minutes,
                resolution_minutes=policy.resolution_minutes,
                business_hours_only=policy.business_hours_only,
                description=policy.description,
            )
        )
    session.flush()


def _worker(service: TicketService, ticket: Ticket, rng: random.Random) -> User:
    """Agente que trabaja el ticket: el asignado o uno del nivel."""
    if ticket.assignee is not None:
        return ticket.assignee
    agents = [
        u
        for u in service.session.scalars(select(User).where(User.is_active.is_(True))).all()
        if u.role.value == f"agente_{ticket.level.value.lower()}"
    ]
    return rng.choice(agents)


def _simulate_ticket(
    service: TicketService,
    clock: FrozenClock,
    rng: random.Random,
    requester: User,
    created_at: datetime,
    now: datetime,
    keep_open: bool,
) -> Ticket:
    template = rng.choice(TICKET_TEMPLATES)
    impact, urgency = template.impact, template.urgency
    if rng.random() < 0.15:
        impact = rng.choice(["alto", "medio", "bajo"])
    clock.set(created_at)
    ticket, _ = service.create_ticket(
        requester,
        title=template.title,
        description=template.description,
        impact=impact,
        urgency=urgency,
    )
    policy = service.sla.policy_for(ticket.priority)
    calendar = service.sla.calendar_for(ticket.priority)

    def at(business_seconds: float) -> datetime:
        target = calendar.add_business_seconds(created_at, business_seconds)
        return max(target, clock.now() + timedelta(minutes=1))

    # Primera respuesta: la mayoría dentro del objetivo
    response_target = policy.first_response_minutes * 60
    factor = rng.uniform(0.1, 0.9) if rng.random() < 0.88 else rng.uniform(1.1, 3.0)
    response_at = at(response_target * factor)
    if keep_open and response_at > now:
        return ticket  # todavía sin respuesta
    clock.set(response_at)
    service.transition(ticket, _worker(service, ticket, rng), TicketStatus.EN_PROGRESO)

    resolution_target = policy.resolution_minutes * 60
    met = rng.random() < 0.84
    progress = rng.uniform(0.2, 0.95) if met else rng.uniform(1.05, 2.2)

    # Pedido de información al usuario (pausa del reloj)
    if rng.random() < 0.25:
        clock.set(at(resolution_target * progress * 0.3))
        if keep_open and clock.now() > now:
            return ticket
        agent = _worker(service, ticket, rng)
        service.add_comment(ticket, agent, rng.choice(WAITING_QUESTIONS), internal=False)
        service.transition(ticket, agent, TicketStatus.EN_ESPERA_USUARIO)
        if keep_open and rng.random() < 0.5:
            return ticket
        clock.advance(hours=rng.uniform(1, 30))
        if keep_open and clock.now() > now:
            clock.set(now - timedelta(minutes=1))
        service.add_comment(ticket, requester, rng.choice(USER_REPLIES), internal=False)

    # Escalamientos hasta el nivel donde se resuelve este tipo de problema
    target_level = Level(template.resolves_at)
    if ticket.level == Level.N1 and target_level == Level.N1 and rng.random() < 0.08:
        target_level = Level.N2  # algún escalamiento "innecesario" para que el FCR sea realista
    step = 0.35
    while ticket.level.rank < target_level.rank:
        clock.set(at(resolution_target * progress * step))
        if keep_open and clock.now() > now:
            return ticket
        agent = _worker(service, ticket, rng)
        if rng.random() < 0.6:
            service.add_comment(
                ticket, agent, "Se adjuntan logs y pasos de diagnóstico realizados.", internal=True
            )
        service.escalate(ticket, agent, rng.choice(ESCALATION_REASONS))
        clock.advance(minutes=rng.randint(5, 90))
        service.transition(ticket, _worker(service, ticket, rng), TicketStatus.EN_PROGRESO)
        step += 0.2

    resolved_at = at(resolution_target * progress)
    if keep_open and resolved_at > now:
        return ticket
    clock.set(min(resolved_at, now - timedelta(minutes=1)) if keep_open else resolved_at)
    service.transition(
        ticket, _worker(service, ticket, rng), TicketStatus.RESUELTO, resolution=template.resolution
    )

    close_at = clock.now() + timedelta(hours=rng.uniform(2, 72))
    if close_at < now and rng.random() < 0.9:
        clock.set(close_at)
        service.transition(
            ticket, requester, TicketStatus.CERRADO, note="Confirmado por el usuario"
        )
    return ticket


def _create_articles(session: Session, author: User, now: datetime) -> int:
    for data in KB_ARTICLES:
        resolved_ids = session.scalars(
            select(Ticket.id)
            .where(
                Ticket.category == data["category"],
                Ticket.status.in_([TicketStatus.RESUELTO, TicketStatus.CERRADO]),
            )
            .order_by(Ticket.id)
            .limit(3)
        ).all()
        knowledge.create_article(
            session,
            author,
            title=str(data["title"]),
            body=str(data["body"]),
            keywords=list(data["keywords"]),  # type: ignore[arg-type]
            category=data["category"],  # type: ignore[arg-type]
            specialty=data["specialty"],  # type: ignore[arg-type]
            ticket_ids=list(resolved_ids),
            now=now,
        )
    return len(KB_ARTICLES)


def seed(settings: Settings, *, total: int = 200, recent: int = 28, rng_seed: int = 42) -> dict:
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    now = SystemClock().now()
    rng = random.Random(rng_seed)
    config = load_sla_config(settings.sla_config_path)
    tz = config.calendar.tz

    with factory() as session:
        users = _create_users(session, now)
        _create_policies(session, settings)
        clock = FrozenClock(now)
        service = TicketService(
            session=session,
            clock=clock,
            sla=SlaEngine.from_session(config, session),
            notifier=Notifier([]),  # quedan en la bandeja interna, sin enviar mails
            classifier=build_classifier(settings),
        )
        requesters = [u for u in users.values() if u.role == Role.SOLICITANTE]
        times = _creation_times(rng, now, total, tz, recent)
        skipped = 0
        for index, created_at in enumerate(times):
            keep_open = index >= total - recent
            try:
                _simulate_ticket(
                    service, clock, rng, rng.choice(requesters), created_at, now, keep_open
                )
            except ServiceError as exc:  # no debería pasar, pero no frena la carga
                skipped += 1
                logger.warning("Ticket de demo omitido: %s", exc.detail)
            if index % 25 == 0:
                session.flush()
        session.commit()

        supervisor = users["supervisor@example.com"]
        articles = _create_articles(session, supervisor, now)
        session.commit()

        # Corrida real del job de SLA sobre los tickets abiertos
        clock.set(now)
        report = SlaMonitor(service).run()
        session.commit()

        totals = {
            "users": len(users),
            "tickets": session.scalar(select(func.count(Ticket.id))),
            "open": session.scalar(
                select(func.count(Ticket.id)).where(
                    Ticket.status.notin_([TicketStatus.RESUELTO, TicketStatus.CERRADO])
                )
            ),
            "articles": articles,
            "skipped": skipped,
            "sla_check": report.as_dict(),
        }
    engine.dispose()
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga datos de demo")
    parser.add_argument("--reset", action="store_true", help="borra todos los datos antes")
    parser.add_argument("--if-empty", action="store_true", help="no hace nada si ya hay datos")
    parser.add_argument(
        "--create-tables", action="store_true", help="crea las tablas sin Alembic (solo dev)"
    )
    parser.add_argument("--tickets", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    settings = get_settings()
    engine = build_engine(settings.database_url)
    if args.create_tables:
        Base.metadata.create_all(engine)
    with build_session_factory(engine)() as session:
        has_data = (session.scalar(select(func.count(User.id))) or 0) > 0
        if has_data and args.reset:
            _clear(session)
        elif has_data:
            print("La base ya tiene datos. Usá --reset para recargarla.")
            return 0 if args.if_empty else 1
    engine.dispose()

    totals = seed(
        settings, total=args.tickets, recent=max(args.tickets // 5, 1), rng_seed=args.seed
    )
    print("Datos de demo cargados:")
    for key, value in totals.items():
        print(f"  {key}: {value}")
    print(f"\nUsuarios de demo (contraseña para todos: {DEMO_PASSWORD}):")
    for email, name, role, _ in DEMO_USERS:
        print(f"  {role:<12} {email:<28} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
