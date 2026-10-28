"""Login, usuarios y notificaciones del usuario autenticado."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.deps import ClockDep, CurrentUser, SessionDep, SettingsDep, require_roles
from app.domain.enums import AGENT_ROLES, Role
from app.models import Notification, User, UserSpecialty
from app.schemas import NotificationOut, TokenOut, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/api", tags=["auth"])

SupervisorOnly = Annotated[User, Depends(require_roles(Role.SUPERVISOR))]


@router.post("/auth/login", response_model=TokenOut)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
):
    user = session.scalar(select(User).where(func.lower(User.email) == form.username.lower()))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos")
    token, expires = create_access_token(
        settings, user_id=user.id, role=user.role.value, now=clock.now()
    )
    return TokenOut(access_token=token, expires_at=expires)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: SupervisorOnly, session: SessionDep):
    return session.scalars(select(User).order_by(User.role, User.full_name)).all()


@router.get("/users/agents", response_model=list[UserOut])
def list_agents(user: CurrentUser, session: SessionDep):
    if user.role == Role.SOLICITANTE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tenés permisos para esta acción")
    return session.scalars(
        select(User)
        .where(User.role.in_(list(AGENT_ROLES)), User.is_active.is_(True))
        .order_by(User.role, User.full_name)
    ).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, _: SupervisorOnly, session: SessionDep, clock: ClockDep):
    exists = session.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if exists:
        raise ConflictError("Ya existe un usuario con ese email")
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
        created_at=clock.now(),
    )
    user.specialty_links = [UserSpecialty(specialty=s) for s in dict.fromkeys(payload.specialties)]
    session.add(user)
    session.commit()
    return user


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(user: CurrentUser, session: SessionDep, unread_only: bool = False):
    query = select(Notification).where(Notification.recipient_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    return session.scalars(query.order_by(Notification.id.desc()).limit(50)).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: CurrentUser, session: SessionDep):
    notification = session.get(Notification, notification_id)
    if notification is None or notification.recipient_id != user.id:
        raise NotFoundError("La notificación no existe")
    notification.is_read = True
    session.commit()
    return notification
