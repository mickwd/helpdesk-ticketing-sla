"""Enumeraciones del dominio. Los valores son los que se guardan en la base."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SOLICITANTE = "solicitante"
    AGENTE_N1 = "agente_n1"
    AGENTE_N2 = "agente_n2"
    AGENTE_N3 = "agente_n3"
    SUPERVISOR = "supervisor"


class Specialty(StrEnum):
    REDES = "redes"
    WINDOWS = "windows"
    LINUX = "linux"
    BASES_DE_DATOS = "bases_de_datos"
    APLICACIONES = "aplicaciones"


class Category(StrEnum):
    ACCESO_CUENTAS = "acceso_cuentas"
    RED_CONECTIVIDAD = "red_conectividad"
    HARDWARE = "hardware"
    SOFTWARE = "software"
    CORREO = "correo"
    BASE_DE_DATOS = "base_de_datos"
    SERVIDORES = "servidores"
    IMPRESION = "impresion"
    OTRO = "otro"


class Level(StrEnum):
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"

    @property
    def rank(self) -> int:
        return int(self.value[1])

    def next(self) -> Level | None:
        return {Level.N1: Level.N2, Level.N2: Level.N3}.get(self)

    def previous(self) -> Level | None:
        return {Level.N3: Level.N2, Level.N2: Level.N1}.get(self)


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Impact(StrEnum):
    ALTO = "alto"
    MEDIO = "medio"
    BAJO = "bajo"


class Urgency(StrEnum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class TicketStatus(StrEnum):
    NUEVO = "nuevo"
    ASIGNADO = "asignado"
    EN_PROGRESO = "en_progreso"
    EN_ESPERA_USUARIO = "en_espera_usuario"
    RESUELTO = "resuelto"
    CERRADO = "cerrado"


OPEN_STATUSES = frozenset(
    {
        TicketStatus.NUEVO,
        TicketStatus.ASIGNADO,
        TicketStatus.EN_PROGRESO,
        TicketStatus.EN_ESPERA_USUARIO,
    }
)
DONE_STATUSES = frozenset({TicketStatus.RESUELTO, TicketStatus.CERRADO})

ROLE_LEVEL: dict[Role, Level] = {
    Role.AGENTE_N1: Level.N1,
    Role.AGENTE_N2: Level.N2,
    Role.AGENTE_N3: Level.N3,
}
LEVEL_ROLE: dict[Level, Role] = {v: k for k, v in ROLE_LEVEL.items()}
AGENT_ROLES = frozenset(ROLE_LEVEL)


class EventType(StrEnum):
    CREADO = "creado"
    CLASIFICADO = "clasificado"
    ESTADO = "estado"
    ASIGNACION = "asignacion"
    ESCALAMIENTO = "escalamiento"
    DESESCALAMIENTO = "desescalamiento"
    PRIORIDAD = "prioridad"
    CATEGORIA = "categoria"
    COMENTARIO = "comentario"
    ADJUNTO = "adjunto"
    PRIMERA_RESPUESTA = "primera_respuesta"
    SLA_ADVERTENCIA = "sla_advertencia"
    SLA_INCUMPLIDO = "sla_incumplido"


class NotificationKind(StrEnum):
    SLA_ADVERTENCIA = "sla_advertencia"
    SLA_INCUMPLIDO = "sla_incumplido"
    ESCALAMIENTO = "escalamiento"
    ASIGNACION = "asignacion"
    P1_CRITICO = "p1_critico"
    ACTUALIZACION = "actualizacion"
