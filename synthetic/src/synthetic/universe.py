"""Universo real U: CNE, IQ y GES mapeado: tamaños de lista y problemas GES considerados."""

from dataclasses import dataclass

from synthetic.catalog import ges_specialty_code
from synthetic.targets import Assumptions, CalibrationTargets

NATIONAL_GES_FALLBACK = (136.0, 71.0)  # media y mediana nacionales de retraso (Glosa III-2025)


@dataclass(frozen=True)
class GesInfo:
    """Problema GES mapeado a una especialidad, con sus cifras de calibración."""

    code: int
    name: str
    specialty_code: str
    group: str
    deadline_days: int
    oncologic: bool
    delayed_count: int
    in_deadline_weight: float
    mean_delay_days: float
    median_delay_days: float
    ytd_new_cases: int


@dataclass(frozen=True)
class Universe:
    """Tamaños L del universo real y problemas GES mapeados."""

    l_cne: int
    l_iq: int
    ges: tuple[GesInfo, ...]
    ges_delayed_total: int  # retrasadas nacionales (todas las del reporte)

    @property
    def l_ges_delayed(self) -> int:
        """Garantías retrasadas de los problemas mapeados."""
        return sum(g.delayed_count for g in self.ges)

    @property
    def l_ges(self) -> float:
        """L_GES = retrasadas + en plazo (problemas mapeados)."""
        return self.l_ges_delayed + sum(g.in_deadline_weight for g in self.ges)

    @property
    def total(self) -> float:
        """L_U: tamaño del universo."""
        return self.l_cne + self.l_iq + self.l_ges

    @property
    def ges_coverage(self) -> float:
        """Cobertura de los problemas mapeados sobre las garantías retrasadas nacionales."""
        return self.l_ges_delayed / self.ges_delayed_total


def build_universe(t: CalibrationTargets, a: Assumptions) -> Universe:
    """Calcula L_CNE, L_IQ y los problemas GES mapeados con su L_en_plazo (ley de Little)."""
    factor = float(a.value("ges_in_plazo_factor"))
    by_code = {p.code: p for p in t.ges_problems}
    infos: list[GesInfo] = []
    for m in sorted(a.ges_problem_map, key=lambda x: x.code):
        p = by_code[m.code]
        mean = p.mean_delay_days if p.mean_delay_days is not None else NATIONAL_GES_FALLBACK[0]
        median = (
            p.median_delay_days if p.median_delay_days is not None else NATIONAL_GES_FALLBACK[1]
        )
        ytd = p.ytd_new_cases_fonasa_2025 or 0
        infos.append(
            GesInfo(
                code=m.code,
                name=p.name,
                specialty_code=ges_specialty_code(m.group, m.specialty, t),
                group=m.group,
                deadline_days=m.deadline_days,
                oncologic=m.oncologic,
                delayed_count=p.delayed_count,
                in_deadline_weight=ytd * m.deadline_days / 365.0 * factor,
                mean_delay_days=mean,
                median_delay_days=median,
                ytd_new_cases=ytd,
            )
        )
    return Universe(
        l_cne=t.national_row("consultation").waiting_count,
        l_iq=t.national_row("surgery").waiting_count,
        ges=tuple(infos),
        ges_delayed_total=t.national_row("ges").waiting_count,
    )
