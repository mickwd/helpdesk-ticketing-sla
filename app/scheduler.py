"""Ejecución periódica del chequeo de SLA con APScheduler."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from app.services.escalation import SlaCheckReport, SlaMonitor
from app.services.sla_service import SlaEngine
from app.services.tickets import TicketService

logger = logging.getLogger("helpdesk.scheduler")


def run_sla_job(app: FastAPI) -> SlaCheckReport | None:
    """Abre su propia sesión, corre el monitor y confirma. Nunca propaga errores."""
    state = app.state
    session = state.session_factory()
    try:
        service = TicketService(
            session=session,
            clock=state.clock,
            sla=SlaEngine.from_session(state.sla_config, session),
            notifier=state.notifier,
            classifier=state.classifier,
        )
        report = SlaMonitor(service).run()
        session.commit()
        return report
    except Exception:
        session.rollback()
        logger.exception("Falló el chequeo de SLA")
        return None
    finally:
        session.close()


def start_scheduler(app: FastAPI, interval_seconds: int) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_sla_job,
        "interval",
        seconds=interval_seconds,
        args=[app],
        id="sla_check",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler de SLA iniciado (cada %s s)", interval_seconds)
    return scheduler
