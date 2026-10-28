"""Dependencias de FastAPI: sesión, reloj, servicios y usuario autenticado."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.domain.enums import Role
from app.models import User
from app.security import decode_access_token
from app.services.sla_service import SlaEngine
from app.services.tickets import TicketService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_sla_engine(request: Request, session: SessionDep) -> SlaEngine:
    return SlaEngine.from_session(request.app.state.sla_config, session)


def get_ticket_service(request: Request, session: SessionDep, clock: ClockDep) -> TicketService:
    return TicketService(
        session=session,
        clock=clock,
        sla=SlaEngine.from_session(request.app.state.sla_config, session),
        notifier=request.app.state.notifier,
        classifier=request.app.state.classifier,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas o sesión vencida",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(settings, token, clock.now())
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]
SlaEngineDep = Annotated[SlaEngine, Depends(get_sla_engine)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tenés permisos para esta acción")
        return user

    return checker
