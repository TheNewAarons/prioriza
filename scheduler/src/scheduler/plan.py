"""Plan final: banderas, secuencia, reemplazos, verificación, GES, explicaciones e informe.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Implementa las secciones 7 (causas después de resolver), 9 (postproceso y verificación) y
el informe de equidad de 6.5 de ``docs/scheduler-formulation.md``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import Any

import polars as pl
from shared.disclaimer import DISCLAIMER

from scheduler.config import SchedulerConfig
from scheduler.cpsat import block_counts, block_loads, unmet_ges
from scheduler.greedy import Order, greedy_assign
from scheduler.instance import LOCAL_TZ, SchedulingInstance
from scheduler.phases import STATUS_RANK, SolveOutput, SubResult, run_optimized
from scheduler.prepare import Prepared, place_key, prepare
from scheduler.risk import overflow_risk

# Rango de avisos del historial sintético con que se entrenó el modelo de inasistencias (§4.4).
HISTORY_LEAD_MIN = 7
HISTORY_LEAD_MAX = 90

# Causas de GES no cumplidas después de resolver (§7).
CAPACITY_TAKEN = "capacity_taken"
PATIENT_CONFLICT = "patient_conflict"
SOLVER_LIMIT = "solver_limit"
DECOMPOSITION = "decomposition"
OVERBOOKING_INTERACTION = "overbooking_interaction"

CAUSE_TEXT = {
    "no_block_in_horizon": "no hay ningún bloque de su especialidad y lugar en el horizonte",
    "duration_exceeds_blocks": "la duración del procedimiento no cabe en ningún bloque",
    "deadline_before_first_block": "todos los bloques compatibles caen después del plazo",
    "lead_time": "ningún bloque antes del plazo cumple el aviso mínimo",
    CAPACITY_TAKEN: "todos los bloques que la cumplirían están llenos",
    PATIENT_CONFLICT: "el paciente tiene otra cita en todos los días con cupo libre",
    SOLVER_LIMIT: "hay cupo libre sin conflicto, pero la fase 2 terminó por tiempo",
    DECOMPOSITION: "hay cupo libre sin conflicto, pero la descomposición de respaldo lo usó antes",
    OVERBOOKING_INTERACTION: (
        "hay cupo libre sin conflicto, pero moverla rompe las restricciones de sobrecupo o de "
        "equidad del plan final (R9, R12-R15)"
    ),
}


def code_version() -> str:
    """Versión del paquete ``scheduler`` registrada con cada plan."""
    return f"scheduler-{version('scheduler')}"


@dataclass
class SchedulePlan:
    """Plan de una política: asignaciones, explicaciones, GES e informe."""

    policy: str
    assignments: pl.DataFrame
    explanations: pl.DataFrame
    ges: pl.DataFrame
    standby: pl.DataFrame
    report: dict[str, Any]
    solver_status: str
    objective_value: float | None
    gap: float | None


def _fmt_date(d: date) -> str:
    return d.isoformat()


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


class _Assembler:
    """Arma el plan desde una solución (conjunto de pares) y verifica §9."""

    def __init__(
        self,
        prep: Prepared,
        solution: frozenset[int],
        policy: str,
        subs: list[SubResult] | None,
    ) -> None:
        self.prep = prep
        self.cfg = prep.config
        self.inst = prep.instance
        self.solution = solution
        self.policy = policy
        self.subs = subs or []
        self.entry_pair = {prep.pair_entry[p]: p for p in solution}
        if len(self.entry_pair) != len(solution):
            raise RuntimeError("verificación R1: una entrada quedó en más de un bloque")
        self.loads = block_loads(prep, solution)
        self.counts = block_counts(prep, solution)
        self.sub_of: dict[int, SubResult] = {}
        self.s0: set[int] = set()
        for r in self.subs:
            for i in r.sub.entries:
                self.sub_of[i] = r
            self.s0 |= r.s0
        self.patient_days: dict[str, dict[date, int]] = defaultdict(dict)
        for i, p in self.entry_pair.items():
            day = prep.block(prep.pair_block[p]).local_date
            pd = self.patient_days[prep.entry(i).patient_id]
            if day in pd:
                raise RuntimeError(
                    f"verificación R4: paciente {prep.entry(i).patient_id} con dos citas el {day}"
                )
            pd[day] = i
        self.flags: set[int] = set()
        self.starts: dict[int, datetime] = {}
        self.risks: dict[int, float] = {}

    # ---------------------------------------------------------------- verificación §9

    def verify(self) -> None:
        prep = self.prep
        hs, he = self.inst.horizon_start, prep.horizon_end
        for i, p in self.entry_pair.items():
            e = prep.entry(i)
            b = prep.pair_block[p]
            blk = prep.block(b)
            if blk.specialty_code != e.specialty_code:
                raise RuntimeError(f"verificación §4.1: especialidad distinta en {e.entry_id}")
            if place_key(self.cfg, blk.health_service_code, blk.establishment_code) != place_key(
                self.cfg, e.health_service_code, e.establishment_code
            ):
                raise RuntimeError(f"verificación §4.2: lugar distinto en {e.entry_id}")
            if not hs <= blk.local_date < he:
                raise RuntimeError(f"verificación §4.5: {e.entry_id} fuera del horizonte")
            lead = self.cfg.ges_min_lead_days if i in prep.obligation else self.cfg.min_lead_days
            if blk.local_date < self.inst.as_of + timedelta(days=lead):
                raise RuntimeError(f"verificación §4.4: aviso mínimo no cumplido en {e.entry_id}")
            if prep.pair_load(p) > prep.capacity[b]:
                raise RuntimeError(f"verificación §4.3: duración no cabe en {e.entry_id}")
        alpha = self.cfg.overbooking.alpha
        for b, load in self.loads.items():
            cap = prep.capacity[b]
            if load <= cap:
                continue
            blk = prep.block(b)
            if not blk.is_cne or self.policy != "optimized" or not self.cfg.overbooking.enabled:
                raise RuntimeError(f"verificación R2/R3: bloque {blk.slot_id} sobre capacidad")
            if load - cap > prep.overbook_max[b]:
                raise RuntimeError(f"verificación R7: bloque {blk.slot_id} supera O_b")
            members = [i for i, p in self.entry_pair.items() if prep.pair_block[p] == b]
            if any(prep.pair_load(self.entry_pair[i]) != 1 for i in members):
                raise RuntimeError(f"verificación R7: sobrecupo con u_i > 1 en {blk.slot_id}")
            probs = [prep.pair_p[self.entry_pair[i]] or 0.0 for i in members]
            risk = overflow_risk(probs, cap)
            self.risks[b] = risk
            if risk > alpha + 1e-12:
                raise RuntimeError(
                    f"verificación §9.2: riesgo exacto {risk:.4f} > alpha {alpha} en {blk.slot_id}"
                )
        assigned = set(self.entry_pair)
        if not self.s0 <= assigned:
            raise RuntimeError("verificación §9.3: una entrada de S0 quedó sin agendar")
        for r in self.subs:
            if r.f2 is not None:
                true_unmet = len(unmet_ges(prep, r.sub, r.final))
                if true_unmet > r.f2:
                    raise RuntimeError(
                        f"verificación §9.4: {r.sub.label} incumple {true_unmet} GES > F2*={r.f2}"
                    )
                phase2 = r.phase("2")
                optimal2 = phase2 is not None and phase2.status == "OPTIMAL"
                if optimal2 and true_unmet < r.f2 and not r.added:
                    raise RuntimeError(
                        f"verificación §9.4: {r.sub.label} cumple más GES que el óptimo "
                        "de la fase 2"
                    )

    # ---------------------------------------------------------------- banderas y secuencia §9

    def flag_and_sequence(self) -> pl.DataFrame:
        prep = self.prep
        by_block: dict[int, list[int]] = defaultdict(list)
        for i, p in self.entry_pair.items():
            by_block[prep.pair_block[p]].append(i)
        rows: list[dict[str, Any]] = []
        for b in sorted(by_block, key=lambda b: prep.block(b).slot_id):
            blk = prep.block(b)
            members = sorted(
                by_block[b], key=lambda i: (prep.entry(i).rank, prep.entry(i).entry_id)
            )
            cap = prep.capacity[b]
            n = len(members)
            flagged: list[int] = []
            if blk.is_cne and n > cap:
                o = n - cap
                added = [i for i in members if i not in self.s0]
                if len(added) < o:
                    raise RuntimeError(f"verificación §9.3/R13: sobrecupo de S0 en {blk.slot_id}")
                added.sort(
                    key=lambda i: (
                        -(prep.pair_p[self.entry_pair[i]] or 0.0),
                        prep.s[i],
                        prep.entry(i).entry_id,
                    )
                )
                flagged = added[:o]
            self.flags.update(flagged)
            regular = [i for i in members if i not in flagged]
            starts: dict[int, datetime] = {}
            if blk.is_cne:
                assert blk.unit_min is not None
                offset = blk.prebooked_units
                for j, i in enumerate(regular):
                    starts[i] = blk.start_at + timedelta(minutes=(offset + j) * blk.unit_min)
                for k, i in enumerate(flagged):
                    pos = (k + 1) * cap // (len(flagged) + 1)
                    starts[i] = blk.start_at + timedelta(minutes=(offset + pos) * blk.unit_min)
            else:
                t = blk.start_at + timedelta(minutes=blk.prebooked_min)
                for i in regular:
                    starts[i] = t
                    t += timedelta(minutes=prep.pair_load(self.entry_pair[i]))
            self.starts.update(starts)
            for i in members:
                e = prep.entry(i)
                p = self.entry_pair[i]
                rows.append(
                    {
                        "entry_id": e.entry_id,
                        "patient_id": e.patient_id,
                        "slot_id": blk.slot_id,
                        "specialty_code": e.specialty_code,
                        "resource_kind": blk.resource_kind,
                        "scheduled_start": starts[i],
                        "duration_min": e.duration_min,
                        "lead_days": (blk.local_date - self.inst.as_of).days,
                        "is_overbooked": i in flagged,
                        "predicted_noshow_prob": prep.pair_p[p],
                        "phase_added": self._phase_added(i),
                        "coef": prep.pair_coef[p],
                    }
                )
        schema: dict[str, Any] = {
            "entry_id": pl.String,
            "patient_id": pl.String,
            "slot_id": pl.String,
            "specialty_code": pl.String,
            "resource_kind": pl.String,
            "scheduled_start": pl.Datetime("us", "UTC"),
            "duration_min": pl.Int64,
            "lead_days": pl.Int64,
            "is_overbooked": pl.Boolean,
            "predicted_noshow_prob": pl.Float64,
            "phase_added": pl.String,
            "coef": pl.Int64,
        }
        return (
            pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)
        )

    def _phase_added(self, i: int) -> str:
        if self.policy != "optimized":
            return self.policy
        return "3a" if i in self.s0 else "3b"

    def standby(self) -> pl.DataFrame:
        prep = self.prep
        rows: list[dict[str, Any]] = []
        size = self.cfg.or_standby_size
        if size == 0:
            return pl.DataFrame(
                schema={"slot_id": pl.String, "position": pl.Int64, "entry_id": pl.String}
            )
        cands: dict[int, list[int]] = defaultdict(list)
        for i, b in zip(prep.pair_entry, prep.pair_block, strict=True):
            if not prep.block(b).is_cne and i not in self.entry_pair:
                cands[b].append(i)
        for b in sorted(cands, key=lambda b: prep.block(b).slot_id):
            ranked = sorted(cands[b], key=lambda i: (prep.entry(i).rank, prep.entry(i).entry_id))
            for pos, i in enumerate(ranked[:size], start=1):
                rows.append(
                    {
                        "slot_id": prep.block(b).slot_id,
                        "position": pos,
                        "entry_id": prep.entry(i).entry_id,
                    }
                )
        schema = {"slot_id": pl.String, "position": pl.Int64, "entry_id": pl.String}
        return (
            pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)
        )

    # ---------------------------------------------------------------- GES §7

    def _full(self, b: int, i: int) -> bool:
        prep = self.prep
        pair_load = prep.pair_load(prep.pairs_of_entry[i][0])
        for p in prep.pairs_of_entry[i]:
            if prep.pair_block[p] == b:
                pair_load = prep.pair_load(p)
        return self.loads.get(b, 0) + pair_load > prep.capacity[b]

    def _conflict_all(self, i: int, blocks: list[int]) -> bool:
        prep = self.prep
        days = self.patient_days.get(prep.entry(i).patient_id, {})
        return all(
            prep.block(b).local_date in days and days[prep.block(b).local_date] != i for b in blocks
        )

    def _occupants(self, blocks: list[int], g: int) -> dict[str, int]:
        prep = self.prep
        deadline = prep.entry(g).ges_deadline
        out = {"p1_cedidos": 0, "ges_plazo_anterior_o_igual": 0, "ges_otras": 0, "resto": 0}
        bs = set(blocks)
        for i, p in self.entry_pair.items():
            if prep.pair_block[p] not in bs:
                continue
            e = prep.entry(i)
            if i in prep.q1:
                out["p1_cedidos"] += 1
            elif i in prep.obligation:
                assert e.ges_deadline is not None and deadline is not None
                key = "ges_plazo_anterior_o_igual" if e.ges_deadline <= deadline else "ges_otras"
                out[key] += 1
            else:
                out["resto"] += 1
        return out

    def _post_cause(self, g: int) -> tuple[str, dict[str, int] | None]:
        prep = self.prep
        blocks = sorted({prep.pair_block[p] for p in prep.ges_satisfying.get(g, [])})
        free = [b for b in blocks if not self._full(b, g)]
        if not free:
            return CAPACITY_TAKEN, self._occupants(blocks, g)
        if self._conflict_all(g, free):
            return PATIENT_CONFLICT, None
        r = self.sub_of.get(g)
        if r is None:
            raise RuntimeError(
                f"GES {prep.entry(g).entry_id} sin cumplir con cupo libre en la política "
                f"{self.policy}: error de implementación"
            )
        phase2 = r.phase("2")
        if phase2 is None or phase2.status != "OPTIMAL":
            return SOLVER_LIMIT, None
        if r.sub.decomposition != "component":
            return DECOMPOSITION, None
        if r.phase("3b") is not None:
            return OVERBOOKING_INTERACTION, None
        raise RuntimeError(
            f"GES {prep.entry(g).entry_id} sin cumplir con cupo libre, sin conflicto, fase 2 en "
            f"OPTIMAL y sin sobrecupo: error de implementación (bloques libres: "
            f"{[prep.block(b).slot_id for b in free]})"
        )

    def ges_report(self) -> pl.DataFrame:
        prep = self.prep
        rows: list[dict[str, Any]] = []
        for g in sorted(prep.obligation, key=lambda g: prep.entry(g).entry_id):
            e = prep.entry(g)
            assert e.ges_deadline is not None
            kind = prep.obligation[g]
            p = self.entry_pair.get(g)
            day = prep.block(prep.pair_block[p]).local_date if p is not None else None
            sat = set(prep.ges_satisfying.get(g, []))
            met = g not in prep.ges_presolve and p is not None and p in sat
            on_time = day is not None and day <= e.ges_deadline
            first = prep.first_date.get(g)
            cause: str | None = None
            occupants: dict[str, int] | None = None
            if not met:
                if g in prep.ges_presolve:
                    cause = prep.ges_presolve[g]
                else:
                    cause, occupants = self._post_cause(g)
            text = self._ges_text(g, kind, met, day, first, cause, occupants)
            rows.append(
                {
                    "entry_id": e.entry_id,
                    "obligation": kind,
                    "ges_deadline": e.ges_deadline,
                    "met": met,
                    "on_time": on_time,
                    "scheduled_date": day,
                    "days_late": None if day is None else max(0, (day - e.ges_deadline).days),
                    "first_possible_date": first,
                    "cause": cause,
                    "occupants": None if occupants is None else str(occupants),
                    "text": text,
                }
            )
        schema = {
            "entry_id": pl.String,
            "obligation": pl.String,
            "ges_deadline": pl.Date,
            "met": pl.Boolean,
            "on_time": pl.Boolean,
            "scheduled_date": pl.Date,
            "days_late": pl.Int64,
            "first_possible_date": pl.Date,
            "cause": pl.String,
            "occupants": pl.String,
            "text": pl.String,
        }
        return (
            pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)
        )

    def _ges_text(
        self,
        g: int,
        kind: str,
        met: bool,
        day: date | None,
        first: date | None,
        cause: str | None,
        occupants: dict[str, int] | None,
    ) -> str:
        e = self.prep.entry(g)
        assert e.ges_deadline is not None
        parts = [f"Plazo GES {_fmt_date(e.ges_deadline)}"]
        if kind == "overdue":
            parts.append("vencido antes del horizonte; la obligación es agendarla en el horizonte")
        if first is not None:
            parts.append(f"primer bloque compatible el {_fmt_date(first)}")
        text = "; ".join(parts) + "."
        if cause is not None:
            text += f" No se cumple: {CAUSE_TEXT[cause]}."
            if occupants is not None:
                text += (
                    f" Ocupan esos bloques: {occupants['p1_cedidos']} p1 (cesión), "
                    f"{occupants['ges_plazo_anterior_o_igual']} GES con plazo anterior o igual, "
                    f"{occupants['ges_otras']} otras GES y {occupants['resto']} entradas más."
                )
        if day is None:
            text += " Queda sin agendar."
        else:
            late = (day - e.ges_deadline).days
            if late > 0:
                dias = "día" if late == 1 else "días"
                text += f" Queda agendada el {_fmt_date(day)}, {late} {dias} fuera de plazo."
            else:
                text += f" Queda agendada el {_fmt_date(day)}, dentro de plazo."
        return text

    # ---------------------------------------------------------------- explicación por entrada

    def explanations(self, ges: pl.DataFrame) -> pl.DataFrame:
        prep = self.prep
        ges_text = dict(zip(ges["entry_id"].to_list(), ges["text"].to_list(), strict=True))
        no_pair_text = {
            "no_block_in_horizon": "no hay bloques de su especialidad y lugar en el horizonte",
            "duration_exceeds_blocks": "su procedimiento no cabe en ningún bloque",
            "lead_time": "ningún bloque del horizonte cumple el aviso mínimo",
        }
        rows: list[tuple[str, str, str | None, str]] = []
        for i, e in enumerate(self.inst.entries):
            head = f"Puntaje P4 {_num(e.score)} (puesto {e.rank} en su cola)."
            p = self.entry_pair.get(i)
            detail: str | None = None
            if p is not None:
                blk = prep.block(prep.pair_block[p])
                local = self.starts[i].astimezone(LOCAL_TZ)
                status = "scheduled_overbooked" if i in self.flags else "scheduled"
                text = (
                    f"Agendada el {local:%Y-%m-%d} a las {local:%H:%M} (bloque {blk.slot_id}). "
                    f"{head} Aporte al objetivo {prep.pair_coef[p]} = {prep.s[i]} "
                    f"- anticipación {prep.pair_early[p]} - atraso GES "
                    f"{prep.pair_coef_delay(p)}."
                )
                if self.policy == "optimized" and i not in self.s0:
                    detail = "added_by_overbooking"
                    text += " Entra gracias al sobreagendamiento (no tenía cupo sin sobrecupo)."
                if i in self.flags:
                    text += " Ocupa un sobrecupo (comparte hora con otro paciente)."
                elif blk.is_cne and prep.pair_block[p] in self.risks:
                    text += (
                        f" Su sesión tiene sobrecupo; riesgo de desborde "
                        f"{_num(100 * self.risks[prep.pair_block[p]])} %."
                    )
            elif i in prep.no_pair_reason:
                status = "no_compatible_block"
                detail = prep.no_pair_reason[i]
                text = f"Sin bloque compatible: {no_pair_text[detail]}. {head}"
            elif i in prep.filtered_out:
                status = "not_candidate"
                _, cutoff = prep.filtered_out[i]
                text = (
                    f"No entra al modelo: está después de los primeros {cutoff} candidatos de su "
                    f"cola por orden P4, que ya superan la capacidad del horizonte. {head}"
                )
            else:
                blocks = sorted({prep.pair_block[q] for q in prep.pairs_of_entry[i]})
                free = [b for b in blocks if not self._full(b, i)]
                if not free:
                    status = "capacity_taken"
                    text = (
                        f"Sin cupo: sus {len(blocks)} bloques compatibles quedaron llenos con "
                        f"entradas de mayor prioridad o puntaje. {head}"
                    )
                elif self._conflict_all(i, free):
                    status = "patient_conflict"
                    text = f"El paciente ya tiene otra cita en los días con cupo libre. {head}"
                else:
                    status = "not_selected"
                    text = (
                        f"Hay cupo libre en algún bloque compatible, pero el plan no la incluye "
                        f"(capacidad en minutos, restricciones de sobrecupo o límite de tiempo). "
                        f"{head}"
                    )
            if e.entry_id in ges_text:
                text += " GES: " + ges_text[e.entry_id]
            rows.append((e.entry_id, status, detail, text))
        return pl.DataFrame(
            rows,
            schema={
                "entry_id": pl.String,
                "status": pl.String,
                "detail": pl.String,
                "text": pl.String,
            },
            orient="row",
        )

    # ---------------------------------------------------------------- equidad e informe

    def equity(self) -> list[dict[str, Any]]:
        prep = self.prep
        dims = self.cfg.group_limits.dimensions
        acc: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {
                "entries": 0,
                "candidates": 0,
                "scheduled": 0,
                "scheduled_cne": 0,
                "exposed": 0,
                "flagged": 0,
                "risk_sum": 0.0,
            }
        )
        for i, e in enumerate(self.inst.entries):
            attrs = self.inst.groups.get(e.patient_id, {})
            keys = [(d, attrs[d]) for d in dims if d in attrs] + [("all", "all")]
            p = self.entry_pair.get(i)
            for k in keys:
                a = acc[k]
                a["entries"] += 1
                a["candidates"] += i in prep.candidates
                if p is None:
                    continue
                a["scheduled"] += 1
                b = prep.pair_block[p]
                if prep.block(b).is_cne:
                    a["scheduled_cne"] += 1
                    if b in self.risks:
                        a["exposed"] += 1
                        a["risk_sum"] += self.risks[b]
                    if i in self.flags:
                        a["flagged"] += 1
        out: list[dict[str, Any]] = []
        for (d, v), a in sorted(acc.items()):
            cne = a["scheduled_cne"]
            out.append(
                {
                    "dimension": d,
                    "value": v,
                    "entries": int(a["entries"]),
                    "candidates": int(a["candidates"]),
                    "scheduled": int(a["scheduled"]),
                    "scheduled_rate": a["scheduled"] / a["entries"] if a["entries"] else 0.0,
                    "scheduled_cne": int(cne),
                    "exposure_share": a["exposed"] / cne if cne else 0.0,
                    "flagged_share": a["flagged"] / cne if cne else 0.0,
                    "mean_risk_exposed": a["risk_sum"] / a["exposed"] if a["exposed"] else 0.0,
                }
            )
        return out

    def capacity_by_week(self) -> list[dict[str, Any]]:
        prep = self.prep
        acc: dict[int, dict[str, int]] = defaultdict(
            lambda: {
                "cne_sessions": 0,
                "cne_units": 0,
                "or_blocks": 0,
                "or_minutes": 0,
                "scheduled_cne": 0,
                "scheduled_or": 0,
            }
        )
        for b, blk in enumerate(self.inst.blocks):
            if not prep.block_in_horizon[b]:
                continue
            w = (blk.local_date - self.inst.horizon_start).days // 7
            a = acc[w]
            if blk.is_cne:
                a["cne_sessions"] += 1
                a["cne_units"] += prep.capacity[b]
                a["scheduled_cne"] += self.counts.get(b, 0)
            else:
                a["or_blocks"] += 1
                a["or_minutes"] += prep.capacity[b]
                a["scheduled_or"] += self.counts.get(b, 0)
        return [{"week": w, **acc[w]} for w in sorted(acc)]

    def no_block_by_queue(self) -> list[dict[str, Any]]:
        """Entradas sin bloque compatible, por cola y causa (§4)."""
        prep = self.prep
        acc: dict[tuple[str, str, str], int] = defaultdict(int)
        for i, reason in prep.no_pair_reason.items():
            place, spec = prep.queue[i]
            acc[(place, spec, reason)] += 1
        return [
            {"place": pl_, "specialty_code": sp, "reason": r, "entries": n}
            for (pl_, sp, r), n in sorted(acc.items())
        ]

    def by_duration(self) -> list[dict[str, Any]]:
        """Tasa de agendamiento por tipo y duración del procedimiento (§8.1)."""
        acc: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0])
        for i, e in enumerate(self.inst.entries):
            a = acc[(e.care_type, e.duration_min)]
            a[0] += 1
            a[1] += i in self.prep.pairs_of_entry
            a[2] += i in self.entry_pair
        return [
            {
                "care_type": c,
                "duration_min": d,
                "entries": n,
                "with_compatible_block": k,
                "scheduled": s,
                "scheduled_rate_compatible": s / k if k else 0.0,
            }
            for (c, d), (n, k, s) in sorted(acc.items())
        ]

    def lead_extrapolation(self) -> int:
        """Citas con p cuyo aviso queda fuera del rango del historial (7 a 90 días, §4.4)."""
        return sum(
            1
            for i, p in self.entry_pair.items()
            if self.prep.pair_p[p] is not None
            and not HISTORY_LEAD_MIN
            <= (self.prep.block(self.prep.pair_block[p]).local_date - self.inst.as_of).days
            <= HISTORY_LEAD_MAX
        )


def _solver_summary(subs: list[SubResult]) -> tuple[str, float | None, float | None]:
    """Peor estado, objetivo total y brecha agregada de la última fase de puntaje."""
    if not subs:
        return "NOT_SOLVED", None, None
    worst = "OPTIMAL"
    total = 0.0
    bound = 0.0
    has_bound = True
    for r in subs:
        for ph in r.phases:
            if STATUS_RANK.get(ph.status, 3) > STATUS_RANK.get(worst, 3):
                worst = ph.status
        last = r.phase("3b") or r.phase("3a")
        if last is not None:
            total += last.objective
            if last.bound is None:
                has_bound = False
            else:
                bound += last.bound
    gap = abs(bound - total) / max(1.0, abs(total)) if has_bound else None
    return worst, total, gap


def _build(
    prep: Prepared,
    solution: frozenset[int],
    policy: str,
    subs: list[SubResult] | None,
    warnings: list[str],
    frontier: dict[str, Any] | None,
    discarded: list[SubResult] | None = None,
) -> SchedulePlan:
    asm = _Assembler(prep, solution, policy, subs)
    assignments = asm.flag_and_sequence()
    asm.verify()
    ges = asm.ges_report()
    explanations = asm.explanations(ges)
    standby = asm.standby()
    inst = prep.instance
    cfg = prep.config
    objective: float | None
    gap: float | None
    if subs is None:
        status, objective, gap = (
            "NOT_APPLICABLE",
            float(sum(prep.pair_coef[p] for p in solution)),
            None,
        )
    else:
        status, objective, gap = _solver_summary(subs)
    unmet = ges.filter(~pl.col("met"))
    warnings = list(warnings)
    extrapolated = asm.lead_extrapolation()
    if extrapolated:
        warnings.append(
            f"lead_extrapolation: {extrapolated} citas con aviso fuera de {HISTORY_LEAD_MIN}-"
            f"{HISTORY_LEAD_MAX} días; su p extrapola el modelo de inasistencias"
        )
    report: dict[str, Any] = {
        "disclaimer": DISCLAIMER,
        "policy": policy,
        "as_of": inst.as_of.isoformat(),
        "horizon_start": inst.horizon_start.isoformat(),
        "horizon_end_exclusive": prep.horizon_end.isoformat(),
        "seed": inst.seed,
        "code_version": code_version(),
        "config": cfg.model_dump(mode="json"),
        "config_digest": cfg.digest(),
        "rules_digest": inst.rules_digest,
        "rules_version": inst.rules_version,
        "noshow_model_version": inst.noshow_model_version,
        "solver": {
            "status": status,
            "objective": objective,
            "gap": gap,
            "gap_by_phase": _gap_by_phase(subs or []),
            "status_by_phase": _status_by_phase(subs or []),
            "time": _solver_time(subs or [], discarded or []),
            "subproblems": [_sub_report(r) for r in subs or []],
        },
        "summary": {
            "entries_waiting": len(inst.entries),
            "with_compatible_block": len(prep.pairs_of_entry),
            "candidates": len(prep.candidates),
            "not_candidate": len(prep.filtered_out) if policy == "optimized" else 0,
            "scheduled": assignments.height,
            "q1_scheduled": sum(1 for i in asm.entry_pair if i in prep.q1),
            "scheduled_cne": int((assignments["resource_kind"] == "specialist_agenda").sum()),
            "scheduled_or": int((assignments["resource_kind"] == "operating_room").sum()),
            "overbooked_flags": int(assignments["is_overbooked"].sum()),
            "added_by_overbooking": int((assignments["phase_added"] == "3b").sum()),
            "by_status": dict(explanations.group_by("status").len().sort("status").iter_rows()),
        },
        "ges": {
            "obligated": ges.height,
            "met": int(ges["met"].sum()),
            "unmet": unmet.height,
            "unmet_by_cause": dict(unmet.group_by("cause").len().sort("cause").iter_rows()),
            "on_time": int(ges["on_time"].sum()),
        },
        "overbooking": {
            "alpha": cfg.overbooking.alpha,
            "blocks": [
                {
                    "slot_id": prep.block(b).slot_id,
                    "capacity": prep.capacity[b],
                    "scheduled": asm.counts[b],
                    "overbooked": asm.counts[b] - prep.capacity[b],
                    "risk_exact": r,
                }
                for b, r in sorted(asm.risks.items(), key=lambda t: prep.block(t[0]).slot_id)
            ],
            "max_risk_exact": max(asm.risks.values(), default=0.0),
        },
        "equity": asm.equity(),
        "capacity_by_week": asm.capacity_by_week(),
        "no_compatible_block_by_queue": asm.no_block_by_queue(),
        "scheduled_by_duration": asm.by_duration(),
        "frontier": frontier,
        "warnings": warnings,
    }
    return SchedulePlan(
        policy=policy,
        assignments=assignments,
        explanations=explanations,
        ges=ges,
        standby=standby,
        report=report,
        solver_status=status,
        objective_value=objective,
        gap=gap,
    )


def _solver_time(subs: list[SubResult], discarded: list[SubResult]) -> dict[str, Any]:
    """Tiempo de CP-SAT del plan y de las pasadas que la expansión de frontera reemplazó."""

    def totals(rs: list[SubResult]) -> dict[str, Any]:
        phases = [p for r in rs for p in r.phases]
        return {
            "subproblems": len(rs),
            "phases": len(phases),
            "wall_time_s": sum(p.wall_time_s for p in phases),
            "deterministic_time": sum(p.deterministic_time for p in phases),
        }

    return {"plan": totals(subs), "discarded_first_pass": totals(discarded)}


def _status_by_phase(subs: list[SubResult]) -> dict[str, dict[str, int]]:
    """Conteo de estados de CP-SAT por fase (todas las pasadas)."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in subs:
        for p in r.phases:
            out[p.name][p.status] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def _gap_by_phase(subs: list[SubResult]) -> dict[str, float | None]:
    """Brecha agregada (suma de cotas vs suma de objetivos) de las fases de puntaje 3a y 3b.

    La de 3b suele ser mucho mayor que la de 3a porque las restricciones de sobrecupo con
    indicador dan una relajación lineal débil: mide la cota, no necesariamente la solución.
    """
    out: dict[str, float | None] = {}
    for name in ("3a", "3b"):
        phases = [p for r in subs if (p := r.phase(name)) is not None]  # última pasada
        if not phases or any(p.bound is None for p in phases):
            out[name] = None
            continue
        obj = sum(p.objective for p in phases)
        bnd = sum(p.bound or 0.0 for p in phases)
        out[name] = abs(bnd - obj) / max(1.0, abs(obj))
    return out


def _sub_report(r: SubResult) -> dict[str, Any]:
    return {
        "label": r.sub.label,
        "decomposition": r.sub.decomposition,
        "entries": len(r.sub.entries),
        "pairs": len(r.sub.pairs),
        "blocks": len(r.sub.blocks),
        "budget": r.budget,
        "f1": r.f1,
        "f2": r.f2,
        "z0": r.z0,
        "z3": r.z3,
        "phases": [
            {
                "name": p.name,
                "status": p.status,
                "objective": p.objective,
                "bound": p.bound,
                "gap": p.gap,
                "wall_time_s": p.wall_time_s,
                "deterministic_time": p.deterministic_time,
                "budget": p.budget,
                "variables": p.num_variables,
                "constraints": p.num_constraints,
                "hint": p.hint_source,
            }
            for p in r.phases
        ],
        "fairness_passes": r.fairness_passes,
        "techniques": _techniques(r),
        "warnings": r.warnings,
    }


def _techniques(r: SubResult) -> dict[str, Any]:
    """Efecto de la poda de niveles de sobrecupo y de las clases de simetría (§8.4, §8.6)."""
    ctx = r.ctx
    return {
        # Antes y después de la poda por candidatos; la poda por R13 (depende de S0) no se cuenta.
        "overbooking_levels_nominal": ctx.levels_nominal,
        "overbooking_levels_kept": sum(len(lv) for lv in ctx.levels.values()),
        "overbooking_blocks_eligible": len(ctx.levels),
        "symmetry_block_classes": len(ctx.block_classes[False]),
        "symmetry_blocks_in_classes": sum(len(c) for c in ctx.block_classes[False]),
        "symmetry_entry_classes": len(ctx.entry_classes[False]),
        "symmetry_entries_in_classes": sum(len(c) for c in ctx.entry_classes[False]),
    }


def solve(instance: SchedulingInstance, config: SchedulerConfig | None = None) -> SchedulePlan:
    """Política ``optimized`` (CP-SAT) con informe y verificación."""
    cfg = config or SchedulerConfig()
    out: SolveOutput = run_optimized(instance, cfg)
    return _build(
        out.prep, out.solution, "optimized", out.subs, out.warnings, out.frontier, out.discarded
    )


def greedy_schedule(
    instance: SchedulingInstance,
    config: SchedulerConfig | None = None,
    order: Order = "priority",
) -> SchedulePlan:
    """Políticas de referencia ``fifo`` o ``priority`` (§10), sin CP-SAT ni sobrecupo."""
    cfg = config or SchedulerConfig()
    prep = prepare(instance, cfg)
    prep.candidates = frozenset(prep.pairs_of_entry)
    solution = greedy_assign(prep, prep.pairs_of_entry, order)
    return _build(prep, solution, order, None, [], None)
