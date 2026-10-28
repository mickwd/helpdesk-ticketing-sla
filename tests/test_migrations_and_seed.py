"""Las migraciones reflejan los modelos y el seed genera datos coherentes."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select

from app.config import Settings
from app.db import Base, build_session_factory
from app.domain.enums import TicketStatus
from app.models import KnowledgeArticle, Ticket, TicketEvent, User

ROOT = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_to_base(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")


@pytest.mark.slow
def test_seed_creates_consistent_history(tmp_path):
    from app import seed

    url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")
    settings = Settings(database_url=url, ml_enabled=False, notifiers="")
    totals = seed.seed(settings, total=40, recent=8, rng_seed=7)
    assert totals["tickets"] == 40
    assert totals["skipped"] == 0

    engine = create_engine(url)
    with build_session_factory(engine)() as session:
        assert session.scalar(select(func.count(User.id))) == 15
        assert session.scalar(select(func.count(KnowledgeArticle.id))) > 0
        tickets = session.scalars(select(Ticket)).all()
        for ticket in tickets:
            assert ticket.events, "cada ticket tiene auditoría"
            if ticket.status in (TicketStatus.RESUELTO, TicketStatus.CERRADO):
                assert ticket.resolved_at >= ticket.created_at
                assert ticket.resolution
        assert session.scalar(select(func.count(TicketEvent.id))) > 40 * 4
    engine.dispose()
