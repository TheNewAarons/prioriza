"""Métricas de la simulación (diseño §7): series, resumen, grupos y agregados.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from simulation.config import SimulationConfig
from simulation.world import World

MIN_GROUP_N = 30  # GroupLimitsConfig.min_group_n (diseño §7)
GROUP_DIMS = ("age_group", "insurance", "commune_code")


@dataclass
class PolicyResult:
    """Resultado de una política y réplica: eventos y métricas (diseño §7/§8)."""

    seed: int
    policy: str
    events: list[tuple[int, str, str, str, str]]
    weekly: list[dict[str, Any]]
    summary: dict[str, Any]
    groups: list[dict[str, Any]]
    scheduler: dict[str, Any]


def _quantile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    idx = q * (len(xs) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (idx - lo)


def _on_time(e: Any) -> bool:
    return bool(
        e.state == "resolved" and e.resolved_on is not None and e.resolved_on <= e.ges_deadline
    )


def _gap(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if r[key] is not None]
    return max(vals) - min(vals) if len(vals) >= 2 else None


def _stat(values: list[float]) -> dict[str, Any]:
    return {"median": _quantile(values, 0.5), "p90": _quantile(values, 0.9), "n": len(values)}


def build_result(
    *,
    world: World,
    config: SimulationConfig,
    policy: str,
    seed: int,
    entries: dict[str, Any],
    events: list[tuple[int, str, str, str, str]],
    weekly: list[dict[str, Any]],
    scheduler_weekly: list[dict[str, Any]],
    slot_info: dict[str, dict[str, Any]],
    slot_scheduled: dict[str, int],
    slot_attendees: dict[str, int],
    slot_no_shows: dict[str, int],
    slot_attended_min: dict[str, int],
    slot_no_show_min: dict[str, int],
    slot_scheduled_min: dict[str, int],
    patient_attrs: dict[str, dict[str, str]],
    pred_realized: list[tuple[float, bool]],
    appointments_log: list[dict[str, Any]],
) -> PolicyResult:
    """Resume el estado final en métricas de réplica; ``events`` queda para la conservación."""
    start_date = world.horizon_start
    end_date = world.horizon_start + timedelta(days=config.weeks * 7)
    # Semanas con citas confirmables: la planificación k confirma desde D_k + 7.
    window = (
        start_date + timedelta(days=7),
        start_date + timedelta(days=7 * (config.weeks + config.commit_weeks)),
    )
    waiting = [e for e in entries.values() if e.state == "waiting"]
    booked = [e for e in entries.values() if e.state == "booked"]
    resolved = [e for e in entries.values() if e.state == "resolved"]
    removed = [e for e in entries.values() if e.state == "removed_no_show"]
    abandoned = [e for e in entries.values() if e.state == "abandoned"]

    wait_attended = [float((e.resolved_on - e.entry_date).days) for e in resolved if e.resolved_on]
    stock_final = [float((end_date - e.entry_date).days) for e in waiting + booked]

    ges = [e for e in entries.values() if e.is_ges and e.ges_deadline is not None]
    # Garantías cuyo plazo vence dentro de la simulación: incumplida si no se atendió a tiempo
    # (sigue en lista, se atendió tarde o salió por dos inasistencias).
    due = [e for e in ges if start_date <= e.ges_deadline < end_date]
    ges_breached = sum(1 for e in due if not _on_time(e))
    ges_on_time = sum(1 for e in ges if _on_time(e))
    ges_overdue_at_start = sum(1 for e in ges if e.ges_deadline < start_date)
    ges_overdue_at_end = sum(
        1 for e in ges if e.state in ("waiting", "booked") and e.ges_deadline < end_date
    )

    def cap_units(sid: str) -> int:
        info = slot_info[sid]
        return info["duration_min"] // info["unit_min"] if info["unit_min"] else 0

    in_window = {s for s, i in slot_info.items() if window[0] <= i["local_date"] < window[1]}
    cne_slots = sorted(s for s in in_window if slot_info[s]["resource_kind"] == "specialist_agenda")
    or_slots = sorted(s for s in in_window if slot_info[s]["resource_kind"] == "operating_room")
    cne_cap = sum(cap_units(s) for s in cne_slots)
    cne_attend = sum(min(slot_attendees.get(s, 0), cap_units(s)) for s in cne_slots)
    cne_sched = sum(slot_scheduled.get(s, 0) for s in cne_slots)
    or_dur = sum(slot_info[s]["duration_min"] for s in or_slots)
    or_attend_min = sum(slot_attended_min.get(s, 0) for s in or_slots)
    or_sched_min = sum(slot_scheduled_min.get(s, 0) for s in or_slots)

    # Cupos que se habrían usado si los inasistentes hubieran venido.
    cne_lost = sum(
        min(slot_no_shows.get(s, 0), max(0, cap_units(s) - slot_attendees.get(s, 0)))
        for s in cne_slots
    )
    or_lost = sum(slot_no_show_min.get(s, 0) for s in or_slots)

    overflow_sessions = 0
    overflow_units = 0
    overflow_patients = 0
    overflow_slots: set[str] = set()
    for s in cne_slots:
        over = slot_attendees.get(s, 0) - cap_units(s)
        if over > 0:
            overflow_sessions += 1
            overflow_units += over
            overflow_patients += slot_attendees.get(s, 0)
            overflow_slots.add(s)
    overbooked_slots = {a["slot_id"] for a in appointments_log if a["is_overbooked"]}

    no_slot_at_arrival = sum(
        1
        for e in entries.values()
        if e.arrival_day is not None
        and e.first_planned_day is not None
        and not e.first_planned_scheduled
    )

    cne_noshows = sum(slot_no_shows.get(s, 0) for s in cne_slots)
    cne_attempts = cne_noshows + sum(slot_attendees.get(s, 0) for s in cne_slots)
    or_noshows = sum(slot_no_shows.get(s, 0) for s in or_slots)
    or_attempts = or_noshows + sum(slot_attendees.get(s, 0) for s in or_slots)
    predicted_mean = (
        sum(p for p, _ in pred_realized) / len(pred_realized) if pred_realized else None
    )
    realized_rate = (
        sum(1 for _, no_show in pred_realized if no_show) / len(pred_realized)
        if pred_realized
        else None
    )

    summary = {
        "list_size_final": len(waiting) + len(booked),
        "waiting_final": len(waiting),
        "booked_final": len(booked),
        "arrivals_total": sum(1 for e in entries.values() if e.arrival_day is not None),
        "resolved_total": len(resolved),
        "removed_no_show_total": len(removed),
        "abandoned_total": len(abandoned),
        "wait_attended": _stat(wait_attended),
        "wait_stock_final": _stat(stock_final),
        "ges": {
            "due_in_window": len(due),
            "breached": ges_breached,
            "attended_on_time": ges_on_time,
            "overdue_at_start": ges_overdue_at_start,
            "overdue_at_end": ges_overdue_at_end,
        },
        "slot_use": {
            "cne_utilization": cne_attend / cne_cap if cne_cap else None,
            "or_utilization": or_attend_min / or_dur if or_dur else None,
            "cne_scheduled_occupancy": cne_sched / cne_cap if cne_cap else None,
            "or_scheduled_occupancy": or_sched_min / or_dur if or_dur else None,
        },
        "lost_slots": {"cne_units": cne_lost, "or_minutes": or_lost},
        "overflow": {
            "sessions": overflow_sessions,
            "units": overflow_units,
            "affected_patients": overflow_patients,
        },
        "no_slot_at_arrival": no_slot_at_arrival,
        "no_show": {
            "rate_cne": cne_noshows / cne_attempts if cne_attempts else None,
            "rate_or": or_noshows / or_attempts if or_attempts else None,
            "predicted_mean_cne": predicted_mean,
            "realized_rate_cne_with_prediction": realized_rate,
        },
        "exits": {
            "attended": len(resolved),
            "two_no_shows": len(removed),
            "abandoned": len(abandoned),
        },
    }

    weekly_out = _merge_weekly(weekly, events, config.weeks)
    groups_out = _groups(
        entries,
        patient_attrs,
        appointments_log,
        overbooked_slots,
        overflow_slots,
        (start_date, end_date),
        MIN_GROUP_N,
    )
    scheduler = _scheduler_summary(scheduler_weekly)
    return PolicyResult(
        seed=seed,
        policy=policy,
        events=events,
        weekly=weekly_out,
        summary=summary,
        groups=groups_out,
        scheduler=scheduler,
    )


def _merge_weekly(
    weekly: list[dict[str, Any]], events: list[tuple[int, str, str, str, str]], weeks: int
) -> list[dict[str, Any]]:
    counts = {
        w: {
            "arrivals": 0,
            "attended": 0,
            "resolved": 0,
            "no_shows": 0,
            "removed_no_show": 0,
            "abandoned": 0,
        }
        for w in range(weeks)
    }
    for day, _eid, _frm, _to, cause in events:
        w = day // 7
        if w < 0 or w >= weeks or cause in ("stock", "commit"):
            continue
        if cause == "arrival":
            counts[w]["arrivals"] += 1
        elif cause == "attended":
            counts[w]["attended"] += 1
            counts[w]["resolved"] += 1
        elif cause == "no_show":
            counts[w]["no_shows"] += 1
        elif cause == "two_no_shows":
            counts[w]["removed_no_show"] += 1
        elif cause == "abandon":
            counts[w]["abandoned"] += 1
    return [{**row, **counts[row["week"]]} for row in weekly]


def _groups(
    entries: dict[str, Any],
    patient_attrs: dict[str, dict[str, str]],
    appointments_log: list[dict[str, Any]],
    overbooked_slots: set[str],
    overflow_slots: set[str],
    period: tuple[date, date],
    min_n: int,
) -> list[dict[str, Any]]:
    """Métricas por grupo (dimensiones de P6) con la brecha máxima de tasa de atención."""
    out: list[dict[str, Any]] = []
    for dim in GROUP_DIMS:
        buckets: dict[str, dict[str, Any]] = {}
        for e in entries.values():
            val = patient_attrs.get(e.patient_id, {}).get(dim, "?")
            b = buckets.setdefault(
                val,
                {
                    "entries": 0,
                    "attended": 0,
                    "waits": [],
                    "ges_breached": 0,
                    "removed_no_show": 0,
                    "attempts": 0,
                    "no_shows": 0,
                    "cne_appts": 0,
                    "cne_overbooked": 0,
                    "cne_attend_overflow": 0,
                },
            )
            b["entries"] += 1
            if e.state == "resolved":
                b["attended"] += 1
                if e.resolved_on:
                    b["waits"].append(float((e.resolved_on - e.entry_date).days))
            if (
                e.is_ges
                and e.ges_deadline is not None
                and period[0] <= e.ges_deadline < period[1]
                and not _on_time(e)
            ):
                b["ges_breached"] += 1
            if e.state == "removed_no_show":
                b["removed_no_show"] += 1
        for a in appointments_log:
            val = patient_attrs.get(a["patient_id"], {}).get(dim, "?")
            b = buckets.setdefault(
                val,
                {
                    "entries": 0,
                    "attended": 0,
                    "waits": [],
                    "ges_breached": 0,
                    "removed_no_show": 0,
                    "attempts": 0,
                    "no_shows": 0,
                    "cne_appts": 0,
                    "cne_overbooked": 0,
                    "cne_attend_overflow": 0,
                },
            )
            b["attempts"] += 1
            if not a["attended"]:
                b["no_shows"] += 1
            if a["care_type"] == "consultation":
                b["cne_appts"] += 1
                if a["slot_id"] in overbooked_slots:
                    b["cne_overbooked"] += 1
                if a["attended"] and a["slot_id"] in overflow_slots:
                    b["cne_attend_overflow"] += 1
        rows: list[dict[str, Any]] = []
        for val, b in sorted(buckets.items()):
            if b["entries"] < min_n:
                continue
            rows.append(
                {
                    "value": val,
                    "entries": b["entries"],
                    "attended": b["attended"],
                    "attention_rate": b["attended"] / b["entries"],
                    "wait_attended": _stat(b["waits"]),
                    "ges_breached": b["ges_breached"],
                    "removed_no_show": b["removed_no_show"],
                    "no_show_realized_rate": b["no_shows"] / b["attempts"]
                    if b["attempts"]
                    else None,
                    "overbooking_exposure": b["cne_overbooked"] / b["cne_appts"]
                    if b["cne_appts"]
                    else None,
                    "overflow_share": b["cne_attend_overflow"] / b["cne_appts"]
                    if b["cne_appts"]
                    else None,
                }
            )
        out.append(
            {
                "dimension": dim,
                "min_n": min_n,
                "groups": rows,
                "max_gap_attention_rate": _gap(rows, "attention_rate"),
                "max_gap_overbooking_exposure": _gap(rows, "overbooking_exposure"),
                "max_gap_no_show_realized_rate": _gap(rows, "no_show_realized_rate"),
            }
        )
    return out


def _scheduler_summary(weekly: list[dict[str, Any]]) -> dict[str, Any]:
    status_by_phase: dict[str, dict[str, int]] = {}
    gap_by_phase: dict[str, float] = {}
    for w in weekly:
        for phase, counts in (w.get("status_by_phase") or {}).items():
            acc = status_by_phase.setdefault(str(phase), {})
            for status, n in counts.items():
                acc[str(status)] = acc.get(str(status), 0) + int(n)
        for phase, gap in (w.get("gap_by_phase") or {}).items():
            if gap is not None and (
                str(phase) not in gap_by_phase or gap > gap_by_phase[str(phase)]
            ):
                gap_by_phase[str(phase)] = float(gap)
    max_gap = max((w["max_gap"] for w in weekly if w.get("max_gap") is not None), default=None)
    return {
        "plans": len(weekly),
        "status_by_phase": status_by_phase,
        "gap_by_phase": gap_by_phase,
        "max_gap": max_gap,
        "deterministic_time_total": sum(w.get("deterministic_time") or 0.0 for w in weekly),
        "wall_time_total": sum(w.get("wall_time_s") or 0.0 for w in weekly),
        "weekly": weekly,
    }
