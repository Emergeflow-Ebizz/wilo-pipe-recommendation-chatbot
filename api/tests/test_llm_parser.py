"""Tests for llm_parser, mocking the LLM client so no real API key is needed."""
import json
from unittest.mock import patch

from app.common.llm_client import LLMUnavailableError
from app.common.llm_parser import AmbiguousConfirmationError, parse_answer, parse_yes_no
from app.common.schemas import Question


def test_parse_answer_infers_inch_for_bare_borewell_number():
    question = Question(key="borewell_size", prompt="Borewell Size (mm or Inch)", unit="inch")
    fake_response = json.dumps(
        {"value": 4.0, "unit": "inch", "needs_clarification": False, "clarification_question": None}
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response) as mock_complete:
        result = parse_answer(question, "4")

    assert result.value == 4.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    mock_complete.assert_called_once()


def test_parse_answer_llm_signals_needs_clarification():
    question = Question(key="borewell_size", prompt="Borewell Size (mm or Inch)", unit="inch")
    fake_response = json.dumps(
        {
            "value": None,
            "unit": None,
            "needs_clarification": True,
            "clarification_question": "Did you mean 4 inch or 4 mm?",
        }
    )
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        result = parse_answer(question, "asdf")

    assert result.needs_clarification is True
    assert result.clarification_question


def test_parse_answer_llm_unavailable_falls_back_to_clarification():
    question = Question(key="borewell_size", prompt="Borewell Size (mm or Inch)", unit="inch")
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_answer(question, "4")

    assert result.needs_clarification is True
    assert result.value is None


def test_parse_answer_rule_based_exact_format():
    question = Question(key="borewell_size", prompt="Borewell Size (mm or Inch)", unit="inch")
    result = parse_answer(question, "5 inch")

    assert result.value == 5.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    assert result.clarification_question is None


def test_parse_answer_rule_based_with_spacing():
    question = Question(key="well_depth", prompt="Well Depth (ft or m)", unit="ft")
    result = parse_answer(question, "  150   ft  ")

    assert result.value == 150.0
    assert result.unit == "ft"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_case_insensitive():
    question = Question(key="borewell_size", prompt="Borewell Size (mm or Inch)", unit="inch")
    result = parse_answer(question, "6 MM")

    assert result.value == 6.0
    assert result.unit == "mm"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_no_unit_question():
    question = Question(key="num_floors", prompt="To how many floors above ground level is the water to be delivered?", unit=None)
    result = parse_answer(question, "5")

    assert result.value == 5.0
    assert result.unit is None
    assert result.needs_clarification is False


def test_parse_answer_rule_based_no_unit_with_decimal_rejected():
    question = Question(key="num_floors", prompt="To how many floors above ground level is the water to be delivered?", unit=None)
    with patch("app.common.llm_parser.llm_client.complete", return_value=json.dumps(
        {"value": None, "unit": None, "needs_clarification": True, "clarification_question": "Please provide a whole number"}
    )):
        result = parse_answer(question, "5.5")

    assert result.needs_clarification is True


def test_parse_yes_no_confirmed():
    fake_response = json.dumps({"confirmed": True, "needs_clarification": False})
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        assert parse_yes_no("yes please") is True


def test_parse_yes_no_ambiguous_raises():
    fake_response = json.dumps({"confirmed": None, "needs_clarification": True})
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        try:
            parse_yes_no("maybe")
            assert False, "expected AmbiguousConfirmationError"
        except AmbiguousConfirmationError:
            pass
