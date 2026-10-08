"""Enumeraciones del modelo de datos (valores en minúscula, almacenados como texto)."""

from enum import StrEnum


class AgeGroup(StrEnum):
    """Grupo etario del paciente (no se almacena la fecha de nacimiento)."""

    AGE_0_14 = "0_14"
    AGE_15_19 = "15_19"
    AGE_20_44 = "20_44"
    AGE_45_64 = "45_64"
    AGE_65_PLUS = "65_plus"


class Insurance(StrEnum):
    """Previsión de salud."""

    FONASA_A = "fonasa_a"
    FONASA_B = "fonasa_b"
    FONASA_C = "fonasa_c"
    FONASA_D = "fonasa_d"
    OTHER = "other"


class ClinicalPriority(StrEnum):
    """Prioridad clínica declarada por profesionales (dato de entrada; el sistema no la infiere)."""

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class EntryStatus(StrEnum):
    """Estado de una entrada en lista de espera."""

    WAITING = "waiting"
    SCHEDULED = "scheduled"
    RESOLVED = "resolved"
    REMOVED = "removed"


class ResourceKind(StrEnum):
    """Tipo de recurso programable."""

    OPERATING_ROOM = "operating_room"
    SPECIALIST_AGENDA = "specialist_agenda"


class AppointmentStatus(StrEnum):
    """Estado de una cita."""

    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"


class AppointmentOrigin(StrEnum):
    """Origen de una cita: historial sintético, programador o simulación."""

    HISTORY = "history"
    SCHEDULER = "scheduler"
    SIMULATION = "simulation"


class Policy(StrEnum):
    """Política de programación comparada."""

    FIFO = "fifo"
    PRIORITY = "priority"
    OPTIMIZED = "optimized"


class RunStatus(StrEnum):
    """Estado de carga de una corrida sintética."""

    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    """Estado de revisión humana de un plan (todo plan nace pendiente)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class NoShowScenario(StrEnum):
    """Escenario de inasistencias sintéticas."""

    NEUTRAL = "neutral"
    BASELINE = "baseline"
    SES_GRADIENT = "ses_gradient"
