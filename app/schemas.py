"""Esquemas Pydantic de entrada y salida de la API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    Category,
    EventType,
    Impact,
    Level,
    NotificationKind,
    Priority,
    Role,
    Specialty,
    TicketStatus,
    Urgency,
)
from app.domain.sla import SlaState, SlaStatus
from app.models import Ticket
from app.services.sla_service import SlaEngine


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------- auth / users
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserBrief(ORMModel):
    id: int
    full_name: str
    email: str
    role: Role


class UserOut(UserBrief):
    specialties: list[Specialty] = []
    is_active: bool


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Role
    specialties: list[Specialty] = []


# --------------------------------------------------------------------- SLA
class SlaOut(BaseModel):
    state: SlaState
    percent: float
    target_seconds: float
    elapsed_seconds: float
    remaining_seconds: float
    due_at: datetime | None
    paused: bool
    breached: bool

    @classmethod
    def from_status(cls, status: SlaStatus) -> SlaOut:
        return cls(
            state=status.state,
            percent=status.percent,
            target_seconds=status.target_seconds,
            elapsed_seconds=round(status.elapsed_seconds),
            remaining_seconds=round(status.remaining_seconds),
            due_at=status.due_at,
            paused=status.paused,
            breached=status.breached,
        )


class SlaPolicyOut(BaseModel):
    priority: Priority
    first_response_minutes: int
    resolution_minutes: int
    business_hours_only: bool
    description: str


class SlaPolicyUpdate(BaseModel):
    first_response_minutes: int = Field(gt=0, le=60 * 24 * 30)
    resolution_minutes: int = Field(gt=0, le=60 * 24 * 90)
    business_hours_only: bool = True
    description: str = ""


# ------------------------------------------------------------------ tickets
class TicketCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=10_000)
    impact: Impact
    urgency: Urgency
    category: Category | None = None
    specialty: Specialty | None = None


class TicketUpdate(BaseModel):
    impact: Impact | None = None
    urgency: Urgency | None = None
    category: Category | None = None
    specialty: Specialty | None = None


class TransitionIn(BaseModel):
    status: TicketStatus
    note: str | None = Field(default=None, max_length=2000)
    resolution: str | None = Field(default=None, max_length=10_000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class AssignIn(BaseModel):
    assignee_id: int


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    internal: bool = False


class CommentOut(ORMModel):
    id: int
    body: str
    is_internal: bool
    created_at: datetime
    author: UserBrief


class AttachmentOut(ORMModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class EventOut(ORMModel):
    id: int
    event_type: EventType
    from_value: str | None
    to_value: str | None
    message: str | None
    data: dict[str, Any] | None
    created_at: datetime
    actor: UserBrief | None


class TicketSummary(BaseModel):
    id: int
    title: str
    category: Category
    specialty: Specialty
    priority: Priority
    status: TicketStatus
    level: Level
    requester: UserBrief
    assignee: UserBrief | None
    escalation_count: int
    created_at: datetime
    updated_at: datetime
    sla_response: SlaOut
    sla_resolution: SlaOut


class ArticleBrief(BaseModel):
    id: int
    title: str
    score: float | None = None
    matched: list[str] = []


class TicketDetail(TicketSummary):
    description: str
    impact: Impact
    urgency: Urgency
    resolution: str | None
    classification_source: str
    classification_rule: str | None
    first_responded_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    comments: list[CommentOut]
    attachments: list[AttachmentOut]
    events: list[EventOut]
    suggested_articles: list[ArticleBrief] = []
    allowed_transitions: list[TicketStatus] = []


class TicketPage(BaseModel):
    items: list[TicketSummary]
    total: int


def ticket_summary(ticket: Ticket, engine: SlaEngine, now: datetime) -> TicketSummary:
    sla = engine.evaluate(ticket, now)
    return TicketSummary(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        specialty=ticket.specialty,
        priority=ticket.priority,
        status=ticket.status,
        level=ticket.level,
        requester=UserBrief.model_validate(ticket.requester),
        assignee=UserBrief.model_validate(ticket.assignee) if ticket.assignee else None,
        escalation_count=ticket.escalation_count,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        sla_response=SlaOut.from_status(sla.response),
        sla_resolution=SlaOut.from_status(sla.resolution),
    )


# ----------------------------------------------------------- clasificación
class ClassifyIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=10_000)
    impact: Impact | None = None
    urgency: Urgency | None = None


class ClassifyOut(BaseModel):
    category: Category
    specialty: Specialty
    level: Level
    source: str
    rule: str | None
    score: float
    matched: list[str]
    priority: Priority | None = None
    suggested_articles: list[ArticleBrief] = []


class TicketCreated(BaseModel):
    ticket: TicketDetail
    classification: ClassifyOut


# --------------------------------------------------------- base de conocimiento
class ArticleIn(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    body: str = Field(min_length=20)
    keywords: list[str] = []
    category: Category
    specialty: Specialty | None = None
    ticket_ids: list[int] = []


class ArticleOut(ORMModel):
    id: int
    title: str
    body: str
    keyword_list: list[str]
    category: Category
    specialty: Specialty | None
    ticket_ids: list[int]
    created_at: datetime
    updated_at: datetime


class LinkTicketIn(BaseModel):
    ticket_id: int


# ------------------------------------------------------------ notificaciones
class NotificationOut(ORMModel):
    id: int
    ticket_id: int | None
    kind: NotificationKind
    subject: str
    body: str
    is_read: bool
    created_at: datetime
