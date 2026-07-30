"""Regression tests locking in dewatering rules.py behavior."""
import pytest

from app.use_cases.dewatering.rules import (
    HEAD_SAFETY_FACTOR,
    NoDewateringMatchError,
    _match_head,
    calculate_head,
    normalize_depth_of_pit,
    resolve_dewatering_catalog,
    select_model,
)
from app.common.units import ft_to_m, m_to_ft


def test_normalize_depth_of_pit_ft_passthrough():
    assert normalize_depth_of_pit(10, "ft") == 10


def test_normalize_depth_of_pit_m_converts():
    assert normalize_depth_of_pit(1, "m") == pytest.approx(3.28084)


def test_normalize_depth_of_pit_unknown_unit_raises():
    with pytest.raises(ValueError):
        normalize_depth_of_pit(10, "cm")


def test_calculate_head_applies_safety_factor():
    depth_ft = 10
    expected = ft_to_m(depth_ft * HEAD_SAFETY_FACTOR)
    assert calculate_head(depth_ft) == pytest.approx(expected)


def _model(hp, flows_by_head, art_no=1):
    return {
        "motor_rating": {"hp": hp},
        "performance_curves": [{"head": h, "flow": f} for h, f in flows_by_head.items()],
        "art_no": art_no,
        "phase": None,
    }


def test_match_head_exact():
    catalog = {"A": _model(1.0, {10: 100})}
    assert _match_head(catalog, 10) == 10


def test_match_head_rounds_up():
    catalog = {"A": _model(1.0, {15: 50})}
    assert _match_head(catalog, 10) == 15


def test_match_head_none_when_nothing_high_enough():
    catalog = {"A": _model(1.0, {5: 50})}
    assert _match_head(catalog, 10) is None


def test_select_model_exact_hp_match():
    catalog = {
        "A": _model(1.0, {10: 100}),
        "B": _model(2.0, {10: 80}),
    }
    result = select_model(catalog, 10, desired_hp=2.0)
    assert [name for name, _ in result] == ["B"]


def test_select_model_no_hp_given_uses_lowest_hp():
    catalog = {
        "A": _model(1.0, {10: 100}),
        "B": _model(2.0, {10: 80}),
    }
    result = select_model(catalog, 10, desired_hp=None)
    assert [name for name, _ in result] == ["A"]


def test_select_model_desired_hp_absent_falls_back_to_lowest_hp():
    catalog = {
        "A": _model(1.0, {10: 100}),
        "B": _model(2.0, {10: 80}),
    }
    result = select_model(catalog, 10, desired_hp=5.0)
    assert [name for name, _ in result] == ["A"]


def test_select_model_ties_all_returned():
    catalog = {
        "A": _model(1.0, {10: 100}, art_no=1),
        "B": _model(1.0, {10: 100}, art_no=2),
    }
    result = select_model(catalog, 10, desired_hp=None)
    assert {name for name, _ in result} == {"A", "B"}


def test_resolve_dewatering_catalog_walks_mnc_challenger_initial_waste_in_order():
    catalog, sheet_name, matched_head = resolve_dewatering_catalog(1)
    assert sheet_name == "MNC"


def test_resolve_dewatering_catalog_raises_when_no_sheet_reaches_head():
    with pytest.raises(NoDewateringMatchError):
        resolve_dewatering_catalog(10_000)
