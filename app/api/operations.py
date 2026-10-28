"""Políticas de SLA, chequeo manual del job, métricas y base de conocimiento."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.deps import (
    ClockDep,
    CurrentUser,
    SessionDep,
    SlaEngineDep,
    TicketServiceDep,
    require_roles,
)
from app.domain.enums import Priority, Role
from app.models import KnowledgeArticle, SlaPolicy, User
from app.schemas import (
    ArticleBrief,
    ArticleIn,
    ArticleOut,
    LinkTicketIn,
    SlaPolicyOut,
    SlaPolicyUpdate,
)
from app.services import knowledge, metrics
from app.services import permissions as perms
from app.services.errors import NotFoundError
from app.services.escalation import SlaMonitor

router = APIRouter(prefix="/api")

SupervisorOnly = Annotated[User, Depends(require_roles(Role.SUPERVISOR))]


def _require_staff(user: User) -> None:
    if not perms.is_staff(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo disponible para el equipo de soporte")


# ---------------------------------------------------------------------- SLA
@router.get("/sla/policies", response_model=list[SlaPolicyOut], tags=["sla"])
def sla_policies(_: CurrentUser, engine: SlaEngineDep):
    return [
        SlaPolicyOut(
            priority=p.priority,
            first_response_minutes=p.first_response_minutes,
            resolution_minutes=p.resolution_minutes,
            business_hours_only=p.business_hours_only,
            description=p.description,
        )
        for p in sorted(engine.policies.values(), key=lambda p: p.priority.value)
    ]


@router.put("/sla/policies/{priority}", response_model=SlaPolicyOut, tags=["sla"])
def update_sla_policy(
    priority: Priority, payload: SlaPolicyUpdate, _: SupervisorOnly, session: SessionDep
):
    row = session.scalar(select(SlaPolicy).where(SlaPolicy.priority == priority))
    if row is None:
        row = SlaPolicy(priority=priority)
        session.add(row)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    session.commit()
    return SlaPolicyOut(priority=priority, **payload.model_dump())


@router.post("/sla/check", tags=["sla"])
def run_sla_check(_: SupervisorOnly, service: TicketServiceDep) -> dict[str, Any]:
    """Ejecuta el chequeo de SLA en el momento (el scheduler lo corre cada minuto)."""
    report = SlaMonitor(service).run()
    service.session.commit()
    return report.as_dict()


# ------------------------------------------------------------------ métricas
@router.get("/metrics/overview", tags=["metrics"])
def metrics_overview(
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    _require_staff(user)
    return metrics.overview(session, clock.now(), date_from, date_to)


@router.get("/metrics/sla-compliance", tags=["metrics"])
def metrics_sla(
    user: CurrentUser,
    session: SessionDep,
    group_by: Annotated[str, Query(pattern="^(priority|level|agent)$")] = "priority",
) -> dict[str, Any]:
    _require_staff(user)
    tickets = metrics.load_tickets(session)
    keys = {
        "priority": lambda t: t.priority.value,
        "level": lambda t: t.resolved_level.value if t.resolved_level else None,
        "agent": lambda t: t.resolved_by.full_name if t.resolved_by else None,
    }
    return {
        "group_by": group_by,
        "overall": metrics.sla_compliance(tickets),
        "groups": metrics.compliance_by(tickets, keys[group_by]),
    }


@router.get("/metrics/backlog", tags=["metrics"])
def metrics_backlog(user: CurrentUser, session: SessionDep, clock: ClockDep) -> dict[str, Any]:
    _require_staff(user)
    return metrics.backlog(metrics.load_tickets(session), clock.now())


# ------------------------------------------------------- base de conocimiento
@router.get("/kb/articles", response_model=list[ArticleOut], tags=["kb"])
def list_articles(_: CurrentUser, session: SessionDep):
    return session.scalars(select(KnowledgeArticle).order_by(KnowledgeArticle.title)).all()


@router.get("/kb/articles/{article_id}", response_model=ArticleOut, tags=["kb"])
def get_article(article_id: int, _: CurrentUser, session: SessionDep):
    article = session.get(KnowledgeArticle, article_id)
    if article is None:
        raise NotFoundError("El artículo no existe")
    return article


@router.post(
    "/kb/articles", response_model=ArticleOut, status_code=status.HTTP_201_CREATED, tags=["kb"]
)
def create_article(payload: ArticleIn, user: CurrentUser, session: SessionDep, clock: ClockDep):
    _require_staff(user)
    article = knowledge.create_article(session, user, now=clock.now(), **payload.model_dump())
    session.commit()
    return article


@router.post("/kb/articles/{article_id}/tickets", response_model=ArticleOut, tags=["kb"])
def link_article_ticket(
    article_id: int, payload: LinkTicketIn, user: CurrentUser, session: SessionDep
):
    _require_staff(user)
    article = knowledge.link_ticket(session, article_id, payload.ticket_id)
    session.commit()
    return article


@router.get("/kb/suggest", response_model=list[ArticleBrief], tags=["kb"])
def suggest(q: Annotated[str, Query(min_length=3)], _: CurrentUser, session: SessionDep):
    return [
        ArticleBrief(id=s.article.id, title=s.article.title, score=s.score, matched=s.matched)
        for s in knowledge.suggest_articles(session, q, limit=5)
    ]
