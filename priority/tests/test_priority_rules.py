"""Tests de carga y validación de reglas YAML (priority.rules)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from priority.rules import (
    ALLOWED_FIELDS,
    PROHIBITED_FIELDS,
    RulesError,
    RuleSet,
    load_default_rules,
    parse_rules,
)
from priority_test_support import DEFAULT_RULES_DICT, dump, rules_dict


def _err(d: dict[str, Any] | str) -> str:
    """Parsea y devuelve el mensaje de RulesError (falla si no lanza)."""
    text = d if isinstance(d, str) else dump(d)
    with pytest.raises(RulesError) as exc:
        parse_rules(text)
    return str(exc.value)


def _mut() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_RULES_DICT)


# ---------------------------------------------------------------- carga válida


def test_default_yaml_loads() -> None:
    rules = load_default_rules()
    assert isinstance(rules, RuleSet)
    assert rules.schema_version == 1
    assert [c.field for c in rules.components] == [
        "clinical_priority",
        "wait_days",
        "days_to_ges_deadline",
    ]
    assert sum(c.weight for c in rules.components) == pytest.approx(100)
    assert rules.ges_strict.enabled is True
    assert rules.ges_strict.due_soon_days == 14
    assert rules.ges_strict.order_within == "deadline"
    assert [p.value for p in rules.ges_strict.yield_to_priorities] == ["p1"]


def test_rules_error_is_value_error() -> None:
    assert issubclass(RulesError, ValueError)


def test_yield_to_priorities_empty_is_valid(build_rules: Any) -> None:
    assert tuple(build_rules(yield_to_priorities=[]).ges_strict.yield_to_priorities) == ()


def test_ruleset_is_frozen(default_rules: RuleSet) -> None:
    with pytest.raises((TypeError, ValueError)):
        default_rules.rules_id = "otro"  # type: ignore[misc]


# ------------------------------------------------------------ campos prohibidos


@pytest.mark.parametrize(
    "name",
    [
        "insurance",
        "commune_code",
        "age_group",
        "health_service_code",
        "specialty_code",
        "predicted_noshow_prob",
    ],
)
def test_prohibited_field_names_path_and_reason(name: str) -> None:
    d = _mut()
    d["components"].append({"field": name, "label": "x", "weight": 5})
    msg = _err(d)
    assert name in msg
    assert "components" in msg
    reason = PROHIBITED_FIELDS[name]
    assert reason and reason in msg


def test_prohibited_fields_cover_protected_attributes() -> None:
    for name in ("sex", "ethnicity", "nationality", "insurance", "commune_code", "age_group"):
        assert name in PROHIBITED_FIELDS
    assert not set(PROHIBITED_FIELDS) & set(ALLOWED_FIELDS)


def test_unknown_field_shows_allowed_list() -> None:
    d = _mut()
    d["components"].append({"field": "favorite_color", "label": "x", "weight": 5})
    msg = _err(d)
    assert "favorite_color" in msg
    for allowed in ALLOWED_FIELDS:
        assert allowed in msg


# ------------------------------------------------------------------- pesos


def test_negative_weight() -> None:
    d = _mut()
    d["components"][1]["weight"] = -1
    msg = _err(d)
    assert "components.1.weight" in msg


@pytest.mark.parametrize("raw", [".nan", ".inf", "-.inf"])
def test_nan_and_infinite_weight(raw: str) -> None:
    d = _mut()
    d["components"][1]["weight"] = "PLACEHOLDER"
    text = dump(d).replace("PLACEHOLDER", raw).replace("'" + raw + "'", raw)
    msg = _err(text)
    assert "components.1.weight" in msg


def test_zero_weight_clinical_priority() -> None:
    d = _mut()
    d["components"][0]["weight"] = 0
    assert "components.0.weight" in _err(d)


def test_zero_weight_other_components_is_valid() -> None:
    d = _mut()
    d["components"][1]["weight"] = 0
    parse_rules(dump(d))


# ----------------------------------------------------------------- mapping


def test_mapping_incomplete() -> None:
    d = _mut()
    del d["components"][0]["mapping"]["p3"]
    assert "mapping" in _err(d)


def test_mapping_extra_key() -> None:
    d = _mut()
    d["components"][0]["mapping"]["p5"] = 0.0
    assert "mapping" in _err(d)


def test_mapping_not_monotone() -> None:
    d = _mut()
    d["components"][0]["mapping"].update({"p1": 0.5, "p2": 0.6})
    assert "mapping" in _err(d)


def test_mapping_p1_equals_p4() -> None:
    d = _mut()
    d["components"][0]["mapping"] = {"p1": 0.5, "p2": 0.5, "p3": 0.5, "p4": 0.5}
    assert "mapping" in _err(d)


def test_mapping_out_of_range() -> None:
    d = _mut()
    d["components"][0]["mapping"]["p1"] = 1.5
    assert "mapping" in _err(d)


def test_mapping_equal_adjacent_levels_is_valid() -> None:
    d = _mut()
    d["components"][0]["mapping"] = {"p1": 1.0, "p2": 1.0, "p3": 0.2, "p4": 0.0}
    parse_rules(dump(d))


# -------------------------------------------------------------- esquema/claves


def test_schema_version_2_rejected() -> None:
    d = _mut()
    d["schema_version"] = 2
    assert "schema_version" in _err(d)


def test_extra_top_level_key_rejected() -> None:
    d = _mut()
    d["campo_inventado"] = 1
    assert "campo_inventado" in _err(d)


def test_extra_nested_key_rejected() -> None:
    d = _mut()
    d["components"][1]["surprise"] = 1
    msg = _err(d)
    assert "surprise" in msg
    assert "components.1" in msg


def test_extra_key_in_ges_strict_rejected() -> None:
    d = _mut()
    d["ges_strict"]["otra"] = 1
    msg = _err(d)
    assert "ges_strict" in msg
    assert "otra" in msg


def test_duplicate_yaml_key_rejected() -> None:
    text = dump(DEFAULT_RULES_DICT) + "rules_id: otro\n"
    assert "rules_id" in _err(text)


def test_duplicate_yaml_key_nested_rejected() -> None:
    text = dump(DEFAULT_RULES_DICT).replace(
        "  enabled: true\n", "  enabled: true\n  enabled: false\n"
    )
    assert "enabled" in _err(text)


def test_root_must_be_mapping() -> None:
    with pytest.raises(RulesError):
        parse_rules("- a\n- b\n")


def test_missing_required_key() -> None:
    d = _mut()
    del d["ges_strict"]
    assert "ges_strict" in _err(d)


def test_source_name_in_message() -> None:
    d = _mut()
    d["schema_version"] = 9
    with pytest.raises(RulesError) as exc:
        parse_rules(dump(d), source="mi_archivo.yaml")
    assert "mi_archivo.yaml" in str(exc.value)


# ---------------------------------------------------------------- transforms


def test_ramp_start_below_due_soon_when_strict_enabled() -> None:
    d = rules_dict(enabled=True, due_soon_days=14)
    d["components"][2]["transform"]["start_days"] = 10
    assert "start_days" in _err(d)


def test_ramp_start_below_due_soon_ok_when_strict_disabled() -> None:
    d = rules_dict(enabled=False, due_soon_days=14)
    d["components"][2]["transform"]["start_days"] = 10
    parse_rules(dump(d))


@pytest.mark.parametrize(("start", "end"), [(0, 0), (0, 5), (-3, 10)])
def test_ramp_start_not_greater_than_end(start: int, end: int) -> None:
    d = rules_dict(enabled=False)
    d["components"][2]["transform"].update({"start_days": start, "end_days": end})
    assert "start_days" in _err(d)


@pytest.mark.parametrize(
    "steps",
    [
        [
            {"at_days": 0, "value": 0.0},
            {"at_days": 30, "value": 0.5},
            {"at_days": 30, "value": 0.7},
        ],
        [
            {"at_days": 0, "value": 0.0},
            {"at_days": 60, "value": 0.5},
            {"at_days": 30, "value": 0.7},
        ],
        [{"at_days": 5, "value": 0.0}, {"at_days": 30, "value": 0.5}],
        [{"at_days": 0, "value": 0.5}, {"at_days": 30, "value": 0.2}],
    ],
    ids=["equal-thresholds", "decreasing-thresholds", "first-not-zero", "decreasing-values"],
)
def test_invalid_steps(steps: list[dict[str, float]]) -> None:
    d = _mut()
    d["components"][1]["transform"] = {"type": "steps", "steps": steps}
    msg = _err(d)
    assert "steps" in msg or "at_days" in msg
    assert "components.1.transform" in msg


def test_valid_steps_accepted() -> None:
    d = _mut()
    d["components"][1]["transform"] = {
        "type": "steps",
        "steps": [{"at_days": 0, "value": 0.0}, {"at_days": 30, "value": 0.5}],
    }
    parse_rules(dump(d))


def test_unknown_transform_type() -> None:
    d = _mut()
    d["components"][1]["transform"]["type"] = "exponencial"
    assert "transform" in _err(d)


def test_saturation_days_must_be_positive() -> None:
    d = _mut()
    d["components"][1]["transform"]["saturation_days"] = 0
    assert "saturation_days" in _err(d)


# --------------------------------------------------------------- componentes


def test_duplicate_component() -> None:
    d = _mut()
    d["components"].append(copy.deepcopy(d["components"][1]))
    msg = _err(d)
    assert "wait_days" in msg


def test_missing_clinical_component() -> None:
    d = _mut()
    del d["components"][0]
    assert "clinical_priority" in _err(d)


def test_duplicate_clinical_component() -> None:
    d = _mut()
    d["components"].append(copy.deepcopy(d["components"][0]))
    assert "clinical_priority" in _err(d)


# ---------------------------------------------------------- ges_strict.yield


def test_yield_duplicates_rejected() -> None:
    d = rules_dict(yield_to_priorities=["p1", "p1"])
    assert "yield_to_priorities" in _err(d)


@pytest.mark.parametrize("bad", [["p5"], ["urgent"], ["P1x"], [1], "p1", [None]])
def test_yield_invalid_values_rejected(bad: Any) -> None:
    d = rules_dict(yield_to_priorities=bad)
    assert "yield_to_priorities" in _err(d)


def test_invalid_order_within_and_due_soon() -> None:
    assert "order_within" in _err(rules_dict(order_within="random"))
    assert "due_soon_days" in _err(rules_dict(due_soon_days=-1))
    assert "due_soon_days" in _err(rules_dict(due_soon_days=181))


# -------------------------------------------------------------------- digest


def test_digest_stable_under_key_reordering() -> None:
    d = _mut()
    a = parse_rules(yaml_dump(d, sort_keys=False))
    b = parse_rules(yaml_dump(d, sort_keys=True))
    assert a.digest() == b.digest()
    assert len(a.digest()) == 64


def yaml_dump(d: dict[str, Any], *, sort_keys: bool) -> str:
    """YAML con orden de claves controlado."""
    import yaml

    return yaml.safe_dump(d, sort_keys=sort_keys, allow_unicode=True)


def test_digest_changes_with_content() -> None:
    base = parse_rules(dump(_mut()))
    d = _mut()
    d["components"][1]["weight"] = 36
    assert parse_rules(dump(d)).digest() != base.digest()


def test_digest_includes_yield_to_priorities(build_rules: Any) -> None:
    assert (
        build_rules(yield_to_priorities=[]).digest()
        != build_rules(yield_to_priorities=["p1"]).digest()
    )


def test_digest_is_deterministic(default_rules: RuleSet) -> None:
    assert default_rules.digest() == default_rules.digest()
