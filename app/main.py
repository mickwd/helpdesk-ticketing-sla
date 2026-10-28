"""Punto de entrada de la API (FastAPI)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import __version__
from app.api import auth, operations, tickets
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.domain.state_machine import InvalidTransition
from app.scheduler import start_scheduler
from app.services.classification import build_classifier
from app.services.errors import ServiceError
from app.services.notifications import Notifier, build_notifier
from app.services.sla_service import load_sla_config

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    engine: Engine | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = start_scheduler(app, settings.scheduler_interval_seconds)
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Mesa de ayuda con SLA en horario hábil y escalamiento N1 → N2 → N3.",
        lifespan=lifespan,
    )
    engine = engine or build_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.clock = clock or SystemClock()
    app.state.notifier = notifier or build_notifier(settings)
    app.state.classifier = build_classifier(settings)
    app.state.sla_config = load_sla_config(settings.sla_config_path)

    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(InvalidTransition)
    async def transition_error_handler(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(auth.router)
    app.include_router(tickets.router)
    app.include_router(operations.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
