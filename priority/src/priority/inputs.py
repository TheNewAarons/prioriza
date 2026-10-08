"""Entrada mínima del cálculo de prioridad.

``PriorityInput`` contiene solo los campos permitidos por las reglas. No tiene comuna,
previsión, edad ni servicio de salud: aunque alguien se saltara la validación del YAML, el
cálculo no tendría acceso a esos datos.
"""

from dataclasses import dataclass
from datetime import date

from shared.db.enums import ClinicalPriority


@dataclass(frozen=True, slots=True)
class PriorityInput:
    """Datos de una entrada en lista de espera necesarios para puntuarla."""

    entry_id: str
    clinical_priority: ClinicalPriority
    entry_date: date
    ges_deadline: date | None = None

    def __post_init__(self) -> None:
        """Valida tipos y coherencia de fechas."""
        if not isinstance(self.clinical_priority, ClinicalPriority):
            raise ValueError(
                f"clinical_priority debe ser un ClinicalPriority, no {self.clinical_priority!r}"
            )
        if type(self.entry_date) is not date:
            raise ValueError(
                f"entrada {self.entry_id}: entry_date debe ser date (no datetime ni None), "
                f"no {self.entry_date!r}"
            )
        if self.ges_deadline is not None and type(self.ges_deadline) is not date:
            raise ValueError(
                f"entrada {self.entry_id}: ges_deadline debe ser date o None, "
                f"no {self.ges_deadline!r}"
            )
        if self.ges_deadline is not None and self.ges_deadline < self.entry_date:
            raise ValueError(
                f"entrada {self.entry_id}: el plazo GES ({self.ges_deadline}) no puede ser "
                f"anterior a la fecha de ingreso ({self.entry_date})"
            )

    @property
    def is_ges(self) -> bool:
        """Indica si la entrada tiene garantía GES (plazo definido)."""
        return self.ges_deadline is not None
