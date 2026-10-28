"""Modelos ORM (SQLAlchemy 2.0, estilo tipado)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
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


def str_enum(enum_cls: type[StrEnum], length: int = 32) -> Enum:
    """Enum guardado como VARCHAR con el valor (no el nombre), portable entre motores."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    specialty_links: Mapped[list[UserSpecialty]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def specialties(self) -> list[Specialty]:
        return sorted((link.specialty for link in self.specialty_links), key=lambda s: s.value)


class UserSpecialty(Base):
    __tablename__ = "user_specialties"
    __table_args__ = (UniqueConstraint("user_id", "specialty", name="uq_user_specialty"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    specialty: Mapped[Specialty] = mapped_column(str_enum(Specialty))

    user: Mapped[User] = relationship(back_populates="specialty_links")


class SlaPolicy(Base):
    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    priority: Mapped[Priority] = mapped_column(str_enum(Priority, 4), unique=True)
    first_response_minutes: Mapped[int] = mapped_column(Integer)
    resolution_minutes: Mapped[int] = mapped_column(Integer)
    business_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status_level", "status", "level"),
        Index("ix_tickets_assignee_status", "assignee_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[Category] = mapped_column(str_enum(Category))
    specialty: Mapped[Specialty] = mapped_column(str_enum(Specialty))
    impact: Mapped[Impact] = mapped_column(str_enum(Impact, 8))
    urgency: Mapped[Urgency] = mapped_column(str_enum(Urgency, 8))
    priority: Mapped[Priority] = mapped_column(str_enum(Priority, 4), index=True)
    status: Mapped[TicketStatus] = mapped_column(str_enum(TicketStatus), index=True)
    level: Mapped[Level] = mapped_column(str_enum(Level, 4), index=True)

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    classification_source: Mapped[str] = mapped_column(String(20), default="manual")
    classification_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    # Vencimientos calculados (se recalculan al pausar/reanudar o cambiar prioridad)
    response_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    # Banderas del job de SLA para no notificar ni escalar dos veces
    response_warning_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_warning_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    response_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False)

    escalation_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_level: Mapped[Level | None] = mapped_column(str_enum(Level, 4), nullable=True)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])
    comments: Mapped[list[Comment]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Attachment.created_at"
    )
    events: Mapped[list[TicketEvent]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketEvent.id",
    )
    pauses: Mapped[list[SlaPauseInterval]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SlaPauseInterval.started_at",
        lazy="selectin",
    )


class SlaPauseInterval(Base):
    """Tramos en los que el reloj de SLA estuvo detenido (en_espera_usuario)."""

    __tablename__ = "sla_pauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="pauses")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(lazy="joined")


class Attachment(Base):
    """Solo metadatos: el archivo en sí iría a un almacenamiento de objetos."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")


class TicketEvent(Base):
    """Auditoría: cada cambio sobre un ticket queda registrado acá."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType), index=True)
    from_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    ticket: Mapped[Ticket] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(lazy="joined")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[NotificationKind] = mapped_column(str_enum(NotificationKind))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class KnowledgeArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[Category] = mapped_column(str_enum(Category))
    specialty: Mapped[Specialty | None] = mapped_column(str_enum(Specialty), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())

    tickets: Mapped[list[KnowledgeArticleTicket]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    @property
    def ticket_ids(self) -> list[int]:
        return [link.ticket_id for link in self.tickets]


class KnowledgeArticleTicket(Base):
    """Vincula artículos con los tickets resueltos que los originaron o usaron."""

    __tablename__ = "kb_article_tickets"
    __table_args__ = (UniqueConstraint("article_id", "ticket_id", name="uq_article_ticket"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("kb_articles.id", ondelete="CASCADE"))
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))

    article: Mapped[KnowledgeArticle] = relationship(back_populates="tickets")
