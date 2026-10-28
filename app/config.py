"""Configuración de la aplicación leída desde variables de entorno (.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mesa de Ayuda SLA"
    database_url: str = f"sqlite:///{(BASE_DIR / 'helpdesk.db').as_posix()}"

    jwt_secret: str = "cambiar-este-secreto-en-produccion-32b"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    sla_config_path: Path = BASE_DIR / "config" / "sla.yaml"
    classification_rules_path: Path = BASE_DIR / "config" / "classification_rules.yaml"
    classifier_training_csv: Path = BASE_DIR / "data" / "sample_tickets.csv"
    ml_enabled: bool = True

    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    # Canales de notificación separados por coma: log, email, webhook
    notifiers: str = "log"
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    smtp_from: str = "mesa-de-ayuda@example.com"
    webhook_url: str | None = None

    max_attachment_bytes: int = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
