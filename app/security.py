"""Hash de contraseñas (PBKDF2, librería estándar) y tokens JWT."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

import jwt

from app.config import Settings

DEFAULT_ITERATIONS = 200_000


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)


def create_access_token(
    settings: Settings, *, user_id: int, role: str, now: datetime
) -> tuple[str, datetime]:
    expires = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": expires}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_access_token(settings: Settings, token: str, now: datetime) -> dict[str, Any]:
    """Lanza jwt.PyJWTError si el token es inválido o venció.

    El vencimiento se valida contra el reloj inyectado (no el del sistema) para
    que los tests con tiempo congelado se comporten igual que producción.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": False, "verify_iat": False, "require": ["exp", "sub"]},
    )
    if payload["exp"] < now.timestamp():
        raise jwt.ExpiredSignatureError("El token venció")
    return payload
