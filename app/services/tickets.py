"""Casos de uso sobre tickets: alta, transiciones, asignación, escalamiento.

Toda modificación pasa por acá para garantizar que:
- las transiciones respeten la máquina de estados,
- quede un evento de auditoría por cada cambio,
- los vencimientos de SLA se recalculen.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.domain.enums import (
    Category,
    EventType,
    Impact,
    Level,
    NotificationKind,
    Priority,
    Role,
    Specialty,
    TicketStatus,
    Urgency,
)
from app.domain.priority import compute_priority
from app.domain.state_machine import PAUSED_STATUSES, is_escalable, validate_transition
from app.models import Attachment, Comment, SlaPauseInterval, Ticket, TicketEvent, User
from app.services import permissions as perms
from app.services.assignment import pick_agent
from app.services.classification import ClassificationResult, TicketClassifier
from app.services.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.services.notifications import Notifier
from app.services.sla_service import SlaEngine

MIN_REASON_LENGTH = 10
FIRST_RESPONSE_STATUSES = frozenset(
    {TicketStatus.EN_PROGRESO, TicketStatus.EN_ESPERA_USUARIO, TicketStatus.RESUELTO}
)


@dataclass
class TicketService:
    session: Session
    clock: Clock
    sla: SlaEngine
    notifier: Notifier
    classifier: TicketClassifier

    # ------------------------------------------------------------------ helpers
    def now(self) -> datetime:
        return self.clock.now()

    def get(self, ticket_id: int) -> Ticket:
        ticket = self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise NotFoundError(f"El ticket {ticket_id} no existe")
        return ticket

    def get_for(self, user: User, ticket_id: int) -> Ticket:
        ticket = self.get(ticket_id)
        if not perms.can_view_ticket(user, ticket):
            # 404 y no 403 para no revelar la existencia de tickets ajenos
            raise NotFoundError(f"El ticket {ticket_id} no existe")
        return ticket

    def record_event(
        self,
        ticket: Ticket,
        event_type: EventType,
        actor: User | None,
        *,
        from_value: str | None = None,
        to_value: str | None = None,
        message: str | None = None,
        data: dict | None = None,
    ) -> TicketEvent:
        event = TicketEvent(
            ticket=ticket,
            actor_id=actor.id if actor else None,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
            message=message,
            data=data,
            created_at=self.now(),
        )
        self.session.add(event)
        ticket.updated_at = self.now()
        return event

    def supervisors(self) -> list[User]:
        return list(
            self.session.scalars(
                select(User).where(User.role == Role.SUPERVISOR, User.is_active.is_(True))
            ).all()
        )

    def _require_worker(self, actor: User, ticket: Ticket) -> None:
        if not perms.can_work_ticket(actor, ticket):
            raise PermissionDeniedError("No tenés permisos para operar este ticket")

    def _mark_first_response(self, ticket: Ticket, actor: User) -> None:
        if ticket.first_responded_at is not None or not perms.is_staff(actor):
            return
        ticket.first_responded_at = self.now()
        status = self.sla.response_status(ticket, self.now())
        ticket.response_breached = ticket.response_breached or status.breached
        self.record_event(
            ticket,
            EventType.PRIMERA_RESPUESTA,
            actor,
            message="Primera respuesta registrada",
            data={"sla_cumplido": not status.breached},
        )

    def _set_status(
        self, ticket: Ticket, new_status: TicketStatus, actor: User | None, message: str | None
    ) -> None:
        """Cambia el estado manejando las pausas del reloj de SLA."""
        old = ticket.status
        if old == new_status:
            return
        now = self.now()
        if old in PAUSED_STATUSES and new_status not in PAUSED_STATUSES:
            for pause in ticket.pauses:
                if pause.ended_at is None:
                    pause.ended_at = now
        if new_status in PAUSED_STATUSES and old not in PAUSED_STATUSES:
            ticket.pauses.append(SlaPauseInterval(started_at=now))
        ticket.status = new_status
        self.record_event(
            ticket,
            EventType.ESTADO,
            actor,
            from_value=old.value,
            to_value=new_status.value,
            message=message,
        )

    def _set_assignee(
        self, ticket: Ticket, agent: User | None, actor: User | None, message: str
    ) -> None:
        previous = ticket.assignee
        if previous is not None and agent is not None and previous.id == agent.id:
            return
        ticket.assignee = agent
        ticket.assignee_id = agent.id if agent else None
        if agent is not None:
            agent.last_assigned_at = self.now()
        self.record_event(
            ticket,
            EventType.ASIGNACION,
            actor,
            from_value=previous.email if previous else None,
            to_value=agent.email if agent else None,
            message=message,
        )
        if agent is not None:
            self.notifier.notify(
                self.session,
                kind=NotificationKind.ASIGNACION,
                subject=f"Ticket #{ticket.id} asignado ({ticket.priority.value})",
                body=f"Se te asignó el ticket #{ticket.id}: {ticket.title}",
                recipients=[agent],
                ticket=ticket,
                now=self.now(),
            )

    def _auto_assign(self, ticket: Ticket, actor: User | None, reason: str) -> User | None:
        exclude = [actor.id] if actor is not None and perms.is_agent(actor) else []
        choice = pick_agent(self.session, ticket.level, ticket.specialty, exclude_ids=exclude)
        if choice is None:
            # Si el único agente del nivel es quien escala, se permite asignarle
            choice = pick_agent(self.session, ticket.level, ticket.specialty)
        if choice is None:
            if ticket.assignee_id is not None:
                self._set_assignee(ticket, None, actor, f"{reason}: sin agentes disponibles")
            return None
        detail = "por especialidad" if choice.specialty_match else "sin especialista disponible"
        self._set_assignee(
            ticket,
            choice.agent,
            actor,
            f"{reason} (menor carga {detail}, {choice.load} abiertos)",
        )
        return choice.agent

    # -------------------------------------------------------------------- alta
    def create_ticket(
        self,
        requester: User,
        *,
        title: str,
        description: str,
        impact: Impact,
        urgency: Urgency,
        category: Category | None = None,
        specialty: Specialty | None = None,
        auto_assign: bool = True,
    ) -> tuple[Ticket, ClassificationResult]:
        now = self.now()
        classification = self.classifier.classify(title, description)
        priority = compute_priority(impact, urgency)
        ticket = Ticket(
            title=title.strip(),
            description=description.strip(),
            impact=Impact(impact),
            urgency=Urgency(urgency),
            priority=priority,
            category=Category(category) if category else classification.category,
            specialty=Specialty(specialty) if specialty else classification.specialty,
            level=classification.level,
            status=TicketStatus.NUEVO,
            requester=requester,
            requester_id=requester.id,
            classification_source="manual" if category else classification.source,
            classification_rule=classification.rule,
            created_at=now,
            updated_at=now,
        )
        self.session.add(ticket)
        self.session.flush()
        self.record_event(
            ticket,
            EventType.CREADO,
            requester,
            to_value=TicketStatus.NUEVO.value,
            message=f"Ticket creado con prioridad {priority.value} ({impact} / {urgency})",
        )
        self.record_event(
            ticket,
            EventType.CLASIFICADO,
            None,
            to_value=f"{ticket.category.value}/{ticket.specialty.value}/{ticket.level.value}",
            message=f"Clasificación sugerida por {classification.source}",
            data={
                "regla": classification.rule,
                "coincidencias": classification.matched,
                "puntaje": classification.score,
            },
        )
        self.sla.refresh_due_dates(ticket, now)
        if auto_assign:
            agent = self._auto_assign(ticket, None, "Asignación automática")
            if agent is not None:
                self._set_status(ticket, TicketStatus.ASIGNADO, None, "Asignado automáticamente")
        if priority == Priority.P1:
            self.notifier.notify(
                self.session,
                kind=NotificationKind.P1_CRITICO,
                subject=f"P1 abierto: #{ticket.id} {ticket.title}",
                body=f"Se abrió un incidente crítico ({ticket.category.value}). "
                f"Vence respuesta: {ticket.response_due_at:%d/%m %H:%M} UTC",
                recipients=self.supervisors(),
                ticket=ticket,
                now=now,
            )
        self.session.flush()
        return ticket, classification

    # ------------------------------------------------------------ transiciones
    def transition(
        self,
        ticket: Ticket,
        actor: User,
        to_status: TicketStatus,
        *,
        note: str | None = None,
        resolution: str | None = None,
    ) -> Ticket:
        to_status = TicketStatus(to_status)
        self._check_transition_permission(actor, ticket, to_status)
        validate_transition(ticket.status, to_status)
        now = self.now()

        if to_status == TicketStatus.ASIGNADO:
            if perms.is_agent(actor) and perms.agent_level(actor) == ticket.level:
                self._set_assignee(ticket, actor, actor, "Tomado por el agente")
            elif (
                ticket.assignee_id is None or ticket.status != TicketStatus.NUEVO
            ) and self._auto_assign(ticket, actor, "Reasignación") is None:
                raise ConflictError("No hay agentes disponibles para el nivel del ticket")
        elif (
            to_status == TicketStatus.EN_PROGRESO
            and ticket.assignee_id is None
            and perms.is_agent(actor)
        ):
            self._set_assignee(ticket, actor, actor, "Tomado al iniciar el trabajo")
        elif to_status == TicketStatus.RESUELTO and (
            not resolution or len(resolution.strip()) < MIN_REASON_LENGTH
        ):
            raise ValidationError(
                "Para resolver hay que describir la solución "
                f"(mínimo {MIN_REASON_LENGTH} caracteres)"
            )

        if perms.is_staff(actor) and to_status in FIRST_RESPONSE_STATUSES:
            self._mark_first_response(ticket, actor)

        if ticket.status == TicketStatus.RESUELTO and to_status == TicketStatus.EN_PROGRESO:
            # Reapertura: el reloj de resolución vuelve a correr
            ticket.resolved_at = None
            ticket.resolved_by_id = None
            ticket.resolved_level = None
            message = note or "Ticket reabierto"
        else:
            message = note

        self._set_status(ticket, to_status, actor, message)

        if to_status == TicketStatus.RESUELTO:
            ticket.resolution = resolution.strip() if resolution else None
            ticket.resolved_at = now
            ticket.resolved_by_id = actor.id
            ticket.resolved_level = ticket.level
            status = self.sla.resolution_status(ticket, now)
            ticket.resolution_breached = ticket.resolution_breached or status.breached
            self._notify_requester(
                ticket, f"Tu ticket #{ticket.id} fue resuelto", ticket.resolution
            )
        elif to_status == TicketStatus.CERRADO:
            ticket.closed_at = now
        elif to_status == TicketStatus.EN_ESPERA_USUARIO:
            self._notify_requester(
                ticket,
                f"Tu ticket #{ticket.id} necesita tu respuesta",
                note or "El agente necesita más información para continuar.",
            )

        self.sla.refresh_due_dates(ticket, now)
        self.session.flush()
        return ticket

    def _check_transition_permission(
        self, actor: User, ticket: Ticket, target: TicketStatus
    ) -> None:
        if actor.role == Role.SOLICITANTE:
            allowed = ticket.requester_id == actor.id and ticket.status == TicketStatus.RESUELTO
            if not (allowed and target in {TicketStatus.CERRADO, TicketStatus.EN_PROGRESO}):
                raise PermissionDeniedError(
                    "Como solicitante solo podés cerrar o reabrir un ticket resuelto"
                )
            return
        self._require_worker(actor, ticket)

    def _notify_requester(self, ticket: Ticket, subject: str, body: str | None) -> None:
        self.notifier.notify(
            self.session,
            kind=NotificationKind.ACTUALIZACION,
            subject=subject,
            body=body or "",
            recipients=[ticket.requester],
            ticket=ticket,
            now=self.now(),
        )

    # -------------------------------------------------------------- asignación
    def assign(self, ticket: Ticket, actor: User, assignee_id: int) -> Ticket:
        self._require_worker(actor, ticket)
        if ticket.status in {TicketStatus.RESUELTO, TicketStatus.CERRADO}:
            raise ConflictError("No se puede reasignar un ticket resuelto o cerrado")
        agent = self.session.get(User, assignee_id)
        if agent is None or not agent.is_active or not perms.is_agent(agent):
            raise ValidationError("El usuario indicado no es un agente activo")
        if perms.agent_level(agent) != ticket.level:
            raise ValidationError(
                f"El agente es {perms.agent_level(agent)} y el ticket está en "
                f"{ticket.level.value}; "
                "usá escalar/desescalar para cambiar de nivel"
            )
        self._set_assignee(ticket, agent, actor, "Asignación manual")
        if ticket.status == TicketStatus.NUEVO:
            self._set_status(ticket, TicketStatus.ASIGNADO, actor, None)
        self.session.flush()
        return ticket

    # ---------------------------------------------------------- escalamiento
    def escalate(
        self, ticket: Ticket, actor: User | None, reason: str, *, automatic: bool = False
    ) -> Ticket:
        if not automatic:
            if actor is None:
                raise ValidationError("El escalamiento manual requiere un actor")
            self._require_worker(actor, ticket)
        self._validate_reason(reason)
        if not is_escalable(ticket.status):
            raise ConflictError(f"No se puede escalar un ticket en estado {ticket.status.value}")
        target = ticket.level.next()
        if target is None:
            raise ConflictError("El ticket ya está en N3, no se puede escalar más")
        self._change_level(ticket, actor, target, reason, EventType.ESCALAMIENTO, automatic)
        ticket.escalation_count += 1
        self.session.flush()
        return ticket

    def deescalate(self, ticket: Ticket, actor: User, reason: str) -> Ticket:
        if not perms.can_deescalate(actor, ticket):
            raise PermissionDeniedError("Solo N2, N3 o supervisión pueden desescalar")
        self._validate_reason(reason)
        if not is_escalable(ticket.status):
            raise ConflictError(f"No se puede desescalar un ticket en estado {ticket.status.value}")
        target = ticket.level.previous()
        if target is None:
            raise ConflictError("El ticket ya está en N1")
        self._change_level(ticket, actor, target, reason, EventType.DESESCALAMIENTO, False)
        self.session.flush()
        return ticket

    @staticmethod
    def _validate_reason(reason: str | None) -> None:
        if not reason or len(reason.strip()) < MIN_REASON_LENGTH:
            raise ValidationError(
                f"El motivo es obligatorio (mínimo {MIN_REASON_LENGTH} caracteres)"
            )

    def _change_level(
        self,
        ticket: Ticket,
        actor: User | None,
        target: Level,
        reason: str,
        event_type: EventType,
        automatic: bool,
    ) -> None:
        previous = ticket.level
        ticket.level = target
        verb = "Escalado" if event_type == EventType.ESCALAMIENTO else "Desescalado"
        self.record_event(
            ticket,
            event_type,
            actor,
            from_value=previous.value,
            to_value=target.value,
            message=reason.strip(),
            data={"automatico": automatic},
        )
        agent = self._auto_assign(ticket, actor, f"{verb} a {target.value}")
        new_status = TicketStatus.ASIGNADO if agent else TicketStatus.NUEVO
        self._set_status(ticket, new_status, actor, f"{verb} {previous.value} → {target.value}")

        recipients = [agent] if agent else []
        if ticket.priority == Priority.P1:
            recipients += self.supervisors()
        self.notifier.notify(
            self.session,
            kind=NotificationKind.ESCALAMIENTO,
            subject=f"#{ticket.id} {verb.lower()} a {target.value} ({ticket.priority.value})",
            body=f"{ticket.title}. Motivo: {reason.strip()}",
            recipients=recipients,
            ticket=ticket,
            now=self.now(),
        )
        self.sla.refresh_due_dates(ticket, self.now())

    # ---------------------------------------------------- datos del ticket
    def update_fields(
        self,
        ticket: Ticket,
        actor: User,
        *,
        impact: Impact | None = None,
        urgency: Urgency | None = None,
        category: Category | None = None,
        specialty: Specialty | None = None,
    ) -> Ticket:
        self._require_worker(actor, ticket)
        if ticket.status == TicketStatus.CERRADO:
            raise ConflictError("Un ticket cerrado no se puede modificar")
        if impact or urgency:
            new_impact = Impact(impact or ticket.impact)
            new_urgency = Urgency(urgency or ticket.urgency)
            new_priority = compute_priority(new_impact, new_urgency)
            if new_priority != ticket.priority:
                self.record_event(
                    ticket,
                    EventType.PRIORIDAD,
                    actor,
                    from_value=ticket.priority.value,
                    to_value=new_priority.value,
                    message=f"Impacto {new_impact.value} / urgencia {new_urgency.value}",
                )
            ticket.impact, ticket.urgency, ticket.priority = new_impact, new_urgency, new_priority
        if category or specialty:
            old = f"{ticket.category.value}/{ticket.specialty.value}"
            ticket.category = Category(category or ticket.category)
            ticket.specialty = Specialty(specialty or ticket.specialty)
            new = f"{ticket.category.value}/{ticket.specialty.value}"
            if old != new:
                self.record_event(ticket, EventType.CATEGORIA, actor, from_value=old, to_value=new)
        self.sla.refresh_due_dates(ticket, self.now())
        self.session.flush()
        return ticket

    def add_comment(self, ticket: Ticket, author: User, body: str, *, internal: bool) -> Comment:
        if not body or not body.strip():
            raise ValidationError("El comentario no puede estar vacío")
        if internal and not perms.can_see_internal(author):
            raise PermissionDeniedError("Solo el equipo de soporte puede dejar notas internas")
        if perms.is_staff(author):
            self._require_worker(author, ticket)
        elif ticket.requester_id != author.id:
            raise PermissionDeniedError("No podés comentar tickets de otra persona")
        if ticket.status == TicketStatus.CERRADO:
            raise ConflictError("El ticket está cerrado")

        comment = Comment(
            ticket=ticket,
            author_id=author.id,
            body=body.strip(),
            is_internal=internal,
            created_at=self.now(),
        )
        self.session.add(comment)
        self.record_event(
            ticket,
            EventType.COMENTARIO,
            author,
            to_value="interno" if internal else "publico",
            message=body.strip()[:200],
        )
        if perms.is_staff(author) and not internal:
            self._mark_first_response(ticket, author)
        if (
            author.id == ticket.requester_id
            and ticket.status == TicketStatus.EN_ESPERA_USUARIO
            and not internal
        ):
            # La respuesta del usuario reanuda el reloj automáticamente
            self._set_status(ticket, TicketStatus.EN_PROGRESO, author, "El usuario respondió")
            self.sla.refresh_due_dates(ticket, self.now())
        self.session.flush()
        return comment

    def add_attachment(
        self, ticket: Ticket, author: User, *, filename: str, content_type: str, content: bytes
    ) -> Attachment:
        if not perms.can_view_ticket(author, ticket):
            raise NotFoundError(f"El ticket {ticket.id} no existe")
        attachment = Attachment(
            ticket=ticket,
            uploaded_by_id=author.id,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=self.now(),
        )
        self.session.add(attachment)
        self.record_event(
            ticket,
            EventType.ADJUNTO,
            author,
            to_value=filename[:120],
            message=f"{len(content)} bytes",
        )
        self.session.flush()
        return attachment
