"""Errores de negocio. La capa HTTP los traduce a códigos de estado."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ServiceError):
    status_code = 404


class PermissionDeniedError(ServiceError):
    status_code = 403


class ConflictError(ServiceError):
    status_code = 409


class ValidationError(ServiceError):
    status_code = 422
