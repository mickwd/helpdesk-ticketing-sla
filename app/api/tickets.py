"""Endpoints de tickets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import func, or_, select

from app.deps import ClockDep, CurrentUser, SettingsDep, TicketServiceDep
from app.domain.enums import EventType, Level, Priority, Role, TicketStatus
from app.domain.priority import compute_priority
from app.domain.sla import SlaState
from app.domain.state_machine import ALLOWED_TRANSITIONS
from app.models import Ticket, User
from app.schemas import (
    ArticleBrief,
    AssignIn,
    AttachmentOut,
    ClassifyIn,
    ClassifyOut,
    CommentIn,
    CommentOut,
    EventOut,
    ReasonIn,
    TicketCreate,
    TicketCreated,
    TicketDetail,
    TicketPage,
    TicketUpdate,
    TransitionIn,
    ticket_summary,
)
from app.services import permissions as perms
from app.services.classification import ClassificationResult
from app.services.errors import PermissionDeniedError, ValidationError
from app.services.knowledge import suggest_articles
from app.services.tickets import TicketService

router = APIRouter(prefix="/api", tags=["tickets"])


def _allowed_transitions(user: User, ticket: Ticket) -> list[TicketStatus]:
    targets = sorted(ALLOWED_TRANSITIONS[ticket.status], key=lambda s: list(TicketStatus).index(s))
    if user.role == Role.SOLICITANTE:
        if ticket.requester_id != user.id or ticket.status != TicketStatus.RESUELTO:
            return []
        return [t for t in targets if t in {TicketStatus.CERRADO, TicketStatus.EN_PROGRESO}]
    return targets if perms.can_work_ticket(user, ticket) else []


def build_detail(service: TicketService, ticket: Ticket, user: User) -> TicketDetail:
    now = service.now()
    summary = ticket_summary(ticket, service.sla, now)
    internal_ok = perms.can_see_internal(user)
    comments = [c for c in ticket.comments if internal_ok or not c.is_internal]
    events = [
        e
        for e in ticket.events
        if internal_ok
        or not (
            (e.event_type == EventType.COMENTARIO and e.to_value == "interno")
            or e.event_type == EventType.CLASIFICADO
        )
    ]
    suggestions = []
    if internal_ok:
        suggestions = [
            ArticleBrief(id=s.article.id, title=s.article.title, score=s.score, matched=s.matched)
            for s in suggest_articles(service.session, f"{ticket.title} {ticket.description}")
        ]
    return TicketDetail(
        **summary.model_dump(),
        description=ticket.description,
        impact=ticket.impact,
        urgency=ticket.urgency,
        resolution=ticket.resolution,
        classification_source=ticket.classification_source,
        classification_rule=ticket.classification_rule,
        first_responded_at=ticket.first_responded_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        comments=[CommentOut.model_validate(c) for c in comments],
        attachments=[AttachmentOut.model_validate(a) for a in ticket.attachments],
        events=[EventOut.model_validate(e) for e in events],
        suggested_articles=suggestions,
        allowed_transitions=_allowed_transitions(user, ticket),
    )


def _classification_out(result: ClassificationResult, **extra: object) -> ClassifyOut:
    return ClassifyOut(
        category=result.category,
        specialty=result.specialty,
        level=result.level,
        source=result.source,
        rule=result.rule,
        score=result.score,
        matched=result.matched,
        **extra,
    )


@router.post("/tickets", response_model=TicketCreated, status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketCreate, user: CurrentUser, service: TicketServiceDep):
    ticket, classification = service.create_ticket(
        user,
        title=payload.title,
        description=payload.description,
        impact=payload.impact,
        urgency=payload.urgency,
        category=payload.category,
        specialty=payload.specialty,
    )
    service.session.commit()
    suggestions = [
        ArticleBrief(id=s.article.id, title=s.article.title, score=s.score, matched=s.matched)
        for s in suggest_articles(service.session, f"{payload.title} {payload.description}")
    ]
    return TicketCreated(
        ticket=build_detail(service, ticket, user),
        classification=_classification_out(
            classification, priority=ticket.priority, suggested_articles=suggestions
        ),
    )


@router.get("/tickets", response_model=TicketPage)
def list_tickets(
    user: CurrentUser,
    service: TicketServiceDep,
    status_: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    level: Annotated[list[Level] | None, Query()] = None,
    assignee_id: int | None = None,
    mine: bool = False,
    open_only: bool = False,
    q: str | None = None,
    sla: SlaState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = select(Ticket)
    clause = perms.visible_tickets_clause(user)
    if clause is not None:
        query = query.where(clause)
    if status_:
        query = query.where(Ticket.status.in_(status_))
    if open_only:
        query = query.where(Ticket.status.notin_([TicketStatus.RESUELTO, TicketStatus.CERRADO]))
    if priority:
        query = query.where(Ticket.priority.in_(priority))
    if level:
        query = query.where(Ticket.level.in_(level))
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)
    if mine:
        query = query.where(or_(Ticket.assignee_id == user.id, Ticket.requester_id == user.id))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Ticket.title.ilike(pattern), Ticket.description.ilike(pattern)))
    query = query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
    now = service.now()

    if sla is None:
        total = service.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = service.session.scalars(query.limit(limit).offset(offset)).unique().all()
        items = [ticket_summary(t, service.sla, now) for t in rows]
        return TicketPage(items=items, total=total)

    # El estado de SLA se calcula en memoria (depende del calendario hábil)
    summaries = [
        ticket_summary(t, service.sla, now) for t in service.session.scalars(query).unique().all()
    ]
    filtered = [s for s in summaries if s.sla_resolution.state == sla]
    return TicketPage(items=filtered[offset : offset + limit], total=len(filtered))


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: int, user: CurrentUser, service: TicketServiceDep):
    return build_detail(service, service.get_for(user, ticket_id), user)


@router.patch("/tickets/{ticket_id}", response_model=TicketDetail)
def update_ticket(
    ticket_id: int, payload: TicketUpdate, user: CurrentUser, service: TicketServiceDep
):
    ticket = service.get_for(user, ticket_id)
    service.update_fields(ticket, user, **payload.model_dump())
    service.session.commit()
    return build_detail(service, ticket, user)


@router.post("/tickets/{ticket_id}/transition", response_model=TicketDetail)
def transition_ticket(
    ticket_id: int, payload: TransitionIn, user: CurrentUser, service: TicketServiceDep
):
    ticket = service.get_for(user, ticket_id)
    service.transition(
        ticket, user, payload.status, note=payload.note, resolution=payload.resolution
    )
    service.session.commit()
    return build_detail(service, ticket, user)


@router.post("/tickets/{ticket_id}/assign", response_model=TicketDetail)
def assign_ticket(ticket_id: int, payload: AssignIn, user: CurrentUser, service: TicketServiceDep):
    ticket = service.get_for(user, ticket_id)
    service.assign(ticket, user, payload.assignee_id)
    service.session.commit()
    return build_detail(service, ticket, user)


@router.post("/tickets/{ticket_id}/escalate", response_model=TicketDetail)
def escalate_ticket(
    ticket_id: int, payload: ReasonIn, user: CurrentUser, service: TicketServiceDep
):
    ticket = service.get_for(user, ticket_id)
    if user.role == Role.SOLICITANTE:
        raise PermissionDeniedError("Los solicitantes no pueden escalar tickets")
    service.escalate(ticket, user, payload.reason)
    service.session.commit()
    return build_detail(service, ticket, user)


@router.post("/tickets/{ticket_id}/deescalate", response_model=TicketDetail)
def deescalate_ticket(
    ticket_id: int, payload: ReasonIn, user: CurrentUser, service: TicketServiceDep
):
    ticket = service.get_for(user, ticket_id)
    service.deescalate(ticket, user, payload.reason)
    service.session.commit()
    return build_detail(service, ticket, user)


@router.post(
    "/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED
)
def add_comment(ticket_id: int, payload: CommentIn, user: CurrentUser, service: TicketServiceDep):
    ticket = service.get_for(user, ticket_id)
    comment = service.add_comment(ticket, user, payload.body, internal=payload.internal)
    service.session.commit()
    return CommentOut.model_validate(comment)


@router.post(
    "/tickets/{ticket_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    ticket_id: int,
    user: CurrentUser,
    service: TicketServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
):
    ticket = service.get_for(user, ticket_id)
    content = await file.read(settings.max_attachment_bytes + 1)
    if len(content) > settings.max_attachment_bytes:
        raise ValidationError("El archivo supera el tamaño máximo permitido")
    attachment = service.add_attachment(
        ticket,
        user,
        filename=file.filename or "archivo",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    service.session.commit()
    return AttachmentOut.model_validate(attachment)


@router.get("/tickets/{ticket_id}/events", response_model=list[EventOut])
def ticket_events(ticket_id: int, user: CurrentUser, service: TicketServiceDep):
    return build_detail(service, service.get_for(user, ticket_id), user).events


@router.post("/classify", response_model=ClassifyOut)
def classify(payload: ClassifyIn, user: CurrentUser, service: TicketServiceDep, clock: ClockDep):
    """Vista previa de la clasificación y artículos sugeridos (antes de crear el ticket)."""
    result = service.classifier.classify(payload.title, payload.description)
    priority = (
        compute_priority(payload.impact, payload.urgency)
        if payload.impact and payload.urgency
        else None
    )
    suggestions = [
        ArticleBrief(id=s.article.id, title=s.article.title, score=s.score, matched=s.matched)
        for s in suggest_articles(service.session, f"{payload.title} {payload.description}")
    ]
    return _classification_out(result, priority=priority, suggested_articles=suggestions)
