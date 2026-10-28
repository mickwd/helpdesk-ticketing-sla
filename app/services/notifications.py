"""Notificaciones con canales intercambiables (log, email SMTP, webhook).

Cada notificación se guarda en la base (bandeja interna) y además se envía por
los canales configurados en NOTIFIERS. Un canal que falla no corta el flujo.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.enums import NotificationKind
from app.models import Notification, Ticket, User

logger = logging.getLogger("helpdesk.notifications")


@dataclass(frozen=True)
class OutgoingMessage:
    kind: NotificationKind
    subject: str
    body: str
    recipients: list[str]
    ticket_id: int | None = None


class Channel(Protocol):
    name: str

    def send(self, message: OutgoingMessage) -> None: ...


class LogChannel:
    name = "log"

    def send(self, message: OutgoingMessage) -> None:
        logger.info(
            "[%s] %s -> %s | %s",
            message.kind.value,
            message.subject,
            ", ".join(message.recipients) or "(sin destinatarios)",
            message.body,
        )


class EmailChannel:
    name = "email"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutgoingMessage) -> None:
        if not message.recipients:
            return
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self.settings.smtp_from
        email["To"] = ", ".join(message.recipients)
        email.set_content(message.body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_user and self.settings.smtp_password:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(email)


class WebhookChannel:
    """Envía un JSON por POST (compatible con Slack/Teams vía un puente o n8n)."""

    name = "webhook"

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, message: OutgoingMessage) -> None:
        payload = json.dumps(
            {
                "kind": message.kind.value,
                "subject": message.subject,
                "text": message.body,
                "recipients": message.recipients,
                "ticket_id": message.ticket_id,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout):
            pass


@dataclass
class MemoryChannel:
    """Canal en memoria, útil para tests."""

    name: str = "memoria"
    sent: list[OutgoingMessage] = field(default_factory=list)

    def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)


class Notifier:
    def __init__(self, channels: list[Channel]) -> None:
        self.channels = channels

    def notify(
        self,
        session: Session,
        *,
        kind: NotificationKind,
        subject: str,
        body: str,
        recipients: list[User],
        now: datetime,
        ticket: Ticket | None = None,
    ) -> list[Notification]:
        unique = {u.id: u for u in recipients if u is not None}.values()
        rows = [
            Notification(
                recipient_id=user.id,
                ticket_id=ticket.id if ticket else None,
                kind=kind,
                subject=subject,
                body=body,
                created_at=now,
            )
            for user in unique
        ]
        if not rows:
            rows = [
                Notification(
                    recipient_id=None,
                    ticket_id=ticket.id if ticket else None,
                    kind=kind,
                    subject=subject,
                    body=body,
                    created_at=now,
                )
            ]
        session.add_all(rows)
        message = OutgoingMessage(
            kind=kind,
            subject=subject,
            body=body,
            recipients=[u.email for u in unique],
            ticket_id=ticket.id if ticket else None,
        )
        for channel in self.channels:
            try:
                channel.send(message)
            except Exception:
                logger.exception("Falló el canal de notificación %s", channel.name)
        return rows


def build_notifier(settings: Settings) -> Notifier:
    channels: list[Channel] = []
    for name in (n.strip().lower() for n in settings.notifiers.split(",") if n.strip()):
        if name == "log":
            channels.append(LogChannel())
        elif name == "email":
            channels.append(EmailChannel(settings))
        elif name == "webhook":
            if not settings.webhook_url:
                logger.warning("NOTIFIERS incluye webhook pero falta WEBHOOK_URL")
                continue
            channels.append(WebhookChannel(settings.webhook_url))
        else:
            logger.warning("Canal de notificación desconocido: %s", name)
    return Notifier(channels)
