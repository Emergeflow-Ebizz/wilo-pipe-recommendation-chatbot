"""Regression tests locking in existing water_transfer rules.py behavior.

These must keep passing unchanged after the LLM integration is wired in
front of this module - the LLM never alters this logic.
"""
import pytest

from app.use_cases.water_transfer.rules import (
    BorewellOversizeConfirmationRequired,
    BorewellTooSmallError,
    NoModelAvailableError,
    normalize_borewell_size,
    normalize_well_depth,
    resolve_sheet_filename,
    select_model,
)


def test_normalize_borewell_size_inch_passthrough():
    assert normalize_borewell_size(4, "inch") == 4


def test_normalize_borewell_size_mm_converts():
    assert normalize_borewell_size(101.6, "mm") == pytest.approx(4.0)


def test_normalize_borewell_size_unknown_unit_raises():
    with pytest.raises(ValueError):
        normalize_borewell_size(4, "cm")


def test_normalize_well_depth_ft_passthrough():
    assert normalize_well_depth(100, "ft") == 100


def test_normalize_well_depth_m_converts():
    assert normalize_well_depth(1, "m") == pytest.approx(3.28084)


def test_resolve_sheet_filename_too_small_raises():
    with pytest.raises(BorewellTooSmallError):
        resolve_sheet_filename(3.9)


def test_resolve_sheet_filename_too_large_raises():
    with pytest.raises(BorewellOversizeConfirmationRequired):
        resolve_sheet_filename(10.1)


def test_resolve_sheet_filename_exact_and_rounddown():
    assert resolve_sheet_filename(4) == ["WBW-3.json"]
    assert resolve_sheet_filename(6.9) == ["WBW-4 Prathak.json"]
    assert resolve_sheet_filename(8) == ["WBW-6.json", "WBW-7.json"]


def _model(hp, flows_by_head, art_no=1):
    return {
        "motor_rating": {"hp": hp},
        "performance_curves": [{"head": h, "flow": f} for h, f in flows_by_head.items()],
        "art_no": art_no,
        "phase": None,
    }


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


def test_select_model_rounds_up_head():
    catalog = {"A": _model(1.0, {15: 50})}
    result = select_model(catalog, 10, desired_hp=None)
    assert [name for name, _ in result] == ["A"]


def test_select_model_no_head_available_raises():
    catalog = {"A": _model(1.0, {5: 50})}
    with pytest.raises(NoModelAvailableError):
        select_model(catalog, 10, desired_hp=None)
