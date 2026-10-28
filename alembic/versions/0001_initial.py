"""esquema inicial

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28 00:37:15.699784
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "priority",
            sa.Enum("P1", "P2", "P3", "P4", name="priority", native_enum=False, length=4),
            nullable=False,
        ),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("business_hours_only", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("priority"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "solicitante",
                "agente_n1",
                "agente_n2",
                "agente_n3",
                "supervisor",
                name="role",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)
        batch_op.create_index(batch_op.f("ix_users_role"), ["role"], unique=False)

    op.create_table(
        "kb_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("keywords", sa.String(length=500), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "acceso_cuentas",
                "red_conectividad",
                "hardware",
                "software",
                "correo",
                "base_de_datos",
                "servidores",
                "impresion",
                "otro",
                name="category",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "specialty",
            sa.Enum(
                "redes",
                "windows",
                "linux",
                "bases_de_datos",
                "aplicaciones",
                name="specialty",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "acceso_cuentas",
                "red_conectividad",
                "hardware",
                "software",
                "correo",
                "base_de_datos",
                "servidores",
                "impresion",
                "otro",
                name="category",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "specialty",
            sa.Enum(
                "redes",
                "windows",
                "linux",
                "bases_de_datos",
                "aplicaciones",
                name="specialty",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "impact",
            sa.Enum("alto", "medio", "bajo", name="impact", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column(
            "urgency",
            sa.Enum("alta", "media", "baja", name="urgency", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("P1", "P2", "P3", "P4", name="priority", native_enum=False, length=4),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "nuevo",
                "asignado",
                "en_progreso",
                "en_espera_usuario",
                "resuelto",
                "cerrado",
                name="ticketstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "level",
            sa.Enum("N1", "N2", "N3", name="level", native_enum=False, length=4),
            nullable=False,
        ),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("classification_source", sa.String(length=20), nullable=False),
        sa.Column("classification_rule", sa.String(length=80), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("first_responded_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("response_due_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_due_at", sa.DateTime(), nullable=True),
        sa.Column("response_warning_sent", sa.Boolean(), nullable=False),
        sa.Column("resolution_warning_sent", sa.Boolean(), nullable=False),
        sa.Column("response_breached", sa.Boolean(), nullable=False),
        sa.Column("resolution_breached", sa.Boolean(), nullable=False),
        sa.Column("escalation_count", sa.Integer(), nullable=False),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "resolved_level",
            sa.Enum("N1", "N2", "N3", name="level", native_enum=False, length=4),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.create_index("ix_tickets_assignee_status", ["assignee_id", "status"], unique=False)
        batch_op.create_index(batch_op.f("ix_tickets_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_tickets_level"), ["level"], unique=False)
        batch_op.create_index(batch_op.f("ix_tickets_priority"), ["priority"], unique=False)
        batch_op.create_index(batch_op.f("ix_tickets_requester_id"), ["requester_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_tickets_status"), ["status"], unique=False)
        batch_op.create_index("ix_tickets_status_level", ["status", "level"], unique=False)

    op.create_table(
        "user_specialties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "specialty",
            sa.Enum(
                "redes",
                "windows",
                "linux",
                "bases_de_datos",
                "aplicaciones",
                name="specialty",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "specialty", name="uq_user_specialty"),
    )
    with op.batch_alter_table("user_specialties", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_specialties_user_id"), ["user_id"], unique=False)

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_attachments_ticket_id"), ["ticket_id"], unique=False)

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_comments_ticket_id"), ["ticket_id"], unique=False)

    op.create_table(
        "kb_article_tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["kb_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "ticket_id", name="uq_article_ticket"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=True),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "sla_advertencia",
                "sla_incumplido",
                "escalamiento",
                "asignacion",
                "p1_critico",
                "actualizacion",
                name="notificationkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_notifications_recipient_id"), ["recipient_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_notifications_ticket_id"), ["ticket_id"], unique=False)

    op.create_table(
        "sla_pauses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sla_pauses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sla_pauses_ticket_id"), ["ticket_id"], unique=False)

    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "creado",
                "clasificado",
                "estado",
                "asignacion",
                "escalamiento",
                "desescalamiento",
                "prioridad",
                "categoria",
                "comentario",
                "adjunto",
                "primera_respuesta",
                "sla_advertencia",
                "sla_incumplido",
                name="eventtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("from_value", sa.String(length=120), nullable=True),
        sa.Column("to_value", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ticket_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ticket_events_event_type"), ["event_type"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_ticket_events_ticket_id"), ["ticket_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ticket_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ticket_events_ticket_id"))
        batch_op.drop_index(batch_op.f("ix_ticket_events_event_type"))

    op.drop_table("ticket_events")
    with op.batch_alter_table("sla_pauses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sla_pauses_ticket_id"))

    op.drop_table("sla_pauses")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notifications_ticket_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_recipient_id"))

    op.drop_table("notifications")
    op.drop_table("kb_article_tickets")
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_comments_ticket_id"))

    op.drop_table("comments")
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attachments_ticket_id"))

    op.drop_table("attachments")
    with op.batch_alter_table("user_specialties", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_specialties_user_id"))

    op.drop_table("user_specialties")
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.drop_index("ix_tickets_status_level")
        batch_op.drop_index(batch_op.f("ix_tickets_status"))
        batch_op.drop_index(batch_op.f("ix_tickets_requester_id"))
        batch_op.drop_index(batch_op.f("ix_tickets_priority"))
        batch_op.drop_index(batch_op.f("ix_tickets_level"))
        batch_op.drop_index(batch_op.f("ix_tickets_created_at"))
        batch_op.drop_index("ix_tickets_assignee_status")

    op.drop_table("tickets")
    op.drop_table("kb_articles")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_role"))
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
    op.drop_table("sla_policies")
