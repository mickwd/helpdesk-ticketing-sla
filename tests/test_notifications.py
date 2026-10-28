"""Canales de notificación intercambiables."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.config import Settings
from app.domain.enums import NotificationKind
from app.models import Notification
from app.services.notifications import (
    EmailChannel,
    LogChannel,
    MemoryChannel,
    Notifier,
    OutgoingMessage,
    WebhookChannel,
    build_notifier,
)


def test_build_notifier_from_settings():
    settings = Settings(notifiers="log, email, webhook, desconocido", webhook_url="http://x")
    names = [c.name for c in build_notifier(settings).channels]
    assert names == ["log", "email", "webhook"]


def test_webhook_without_url_is_skipped():
    assert build_notifier(Settings(notifiers="webhook", webhook_url=None)).channels == []


class _Broken:
    name = "roto"

    def send(self, message):
        raise ConnectionError("SMTP caído")


def test_failing_channel_does_not_break_flow(session, make_user, clock):
    user = make_user("agente_n1")
    memory = MemoryChannel()
    notifier = Notifier([_Broken(), LogChannel(), memory])
    rows = notifier.notify(
        session,
        kind=NotificationKind.ASIGNACION,
        subject="Asunto",
        body="Cuerpo",
        recipients=[user, user],
        now=clock.now(),
    )
    session.commit()
    assert len(rows) == 1  # destinatarios duplicados se unifican
    assert memory.sent[0].recipients == [user.email]
    assert session.query(Notification).count() == 1


def test_webhook_posts_json():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    channel = WebhookChannel(f"http://127.0.0.1:{server.server_port}/hook")
    channel.send(_message())
    thread.join(timeout=5)
    server.server_close()
    assert received[0]["kind"] == "sla_incumplido"
    assert received[0]["ticket_id"] == 7


def test_email_channel_uses_smtp(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("app.services.notifications.smtplib.SMTP", FakeSMTP)
    EmailChannel(Settings(smtp_use_tls=True, smtp_user="u", smtp_password="p")).send(_message())
    assert sent[0]["To"] == "agente@example.com"
    assert sent[0]["Subject"] == "SLA incumplido"


def _message() -> OutgoingMessage:
    return OutgoingMessage(
        kind=NotificationKind.SLA_INCUMPLIDO,
        subject="SLA incumplido",
        body="El ticket #7 incumplió el SLA",
        recipients=["agente@example.com"],
        ticket_id=7,
    )
