"""Tests for llm_parser, mocking the LLM client so no real API key is needed."""
import json
from unittest.mock import patch

from app.common.llm_client import LLMUnavailableError
from app.common.llm_parser import AmbiguousConfirmationError, parse_answer, parse_yes_no
from app.use_cases.water_transfer.questions import QUESTIONS as WATER_TRANSFER_QUESTIONS

BOREWELL_SIZE = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "borewell_size")
WELL_DEPTH = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "well_depth")
NUM_FLOORS = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "num_floors")
MOTOR_POWER_HP = next(q for q in WATER_TRANSFER_QUESTIONS if q.key == "motor_power_hp")


def _answer_json(**overrides):
    data = {
        "value": None,
        "unit": None,
        "needs_clarification": False,
        "clarification_question": None,
        "skipped": False,
        "redirect_key": None,
        "gave_up": False,
    }
    data.update(overrides)
    return json.dumps(data)


def test_parse_answer_infers_inch_for_bare_borewell_number():
    fake_response = _answer_json(value=4.0, unit="inch")
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response) as mock_complete:
        result = parse_answer(BOREWELL_SIZE, "4")

    assert result.value == 4.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    assert result.confirmation_message == "Got it: 4.0 inch"
    mock_complete.assert_called_once()


def test_parse_answer_llm_signals_needs_clarification():
    extraction = _answer_json(needs_clarification=True)
    clarification_text = "Did you mean 4 inch or 4 mm?"
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ) as mock_complete:
        result = parse_answer(BOREWELL_SIZE, "asdf")

    assert result.needs_clarification is True
    assert result.clarification_question == clarification_text
    assert mock_complete.call_count == 2


def test_parse_answer_llm_unavailable_falls_back_to_clarification():
    with patch("app.common.llm_parser.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = parse_answer(BOREWELL_SIZE, "4")

    assert result.needs_clarification is True
    assert result.value is None


def test_parse_answer_rule_based_exact_format():
    result = parse_answer(BOREWELL_SIZE, "5 inch")

    assert result.value == 5.0
    assert result.unit == "inch"
    assert result.needs_clarification is False
    assert result.clarification_question is None
    assert result.confirmation_message == "Got it: 5.0 inch"


def test_parse_answer_rule_based_with_spacing():
    result = parse_answer(WELL_DEPTH, "  150   ft  ")

    assert result.value == 150.0
    assert result.unit == "ft"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_case_insensitive():
    result = parse_answer(BOREWELL_SIZE, "6 MM")

    assert result.value == 6.0
    assert result.unit == "mm"
    assert result.needs_clarification is False


def test_parse_answer_rule_based_no_unit_question():
    result = parse_answer(NUM_FLOORS, "5")

    assert result.value == 5.0
    assert result.unit is None
    assert result.needs_clarification is False
    assert result.confirmation_message == "Got it: 5.0"


def test_parse_answer_rule_based_no_unit_with_decimal_rejected():
    extraction = _answer_json(value=5.5)
    clarification_text = "Please give a whole number."
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ):
        result = parse_answer(NUM_FLOORS, "5.5")

    assert result.needs_clarification is True
    assert result.value is None
    assert result.clarification_question == clarification_text


def test_parse_answer_gives_up_after_two_attempts_on_any_required_question():
    """num_floors has no unit at all, but the generic 2-attempt give-up
    mechanic must still apply to it - not just the unit-bearing questions."""
    extraction = _answer_json(needs_clarification=True)
    give_up_message = "We can't recommend a pump without this information."
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, give_up_message],
    ):
        result = parse_answer(NUM_FLOORS, "dunno", clarification_attempts=2)

    assert result.gave_up is True
    assert result.value is None
    assert result.clarification_question == give_up_message


def test_parse_answer_non_integer_rejection_uses_llm_generated_message():
    extraction = _answer_json(value=5.5)
    clarification_text = "Whole floors only, please - could you round to the nearest floor?"
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, clarification_text],
    ):
        result = parse_answer(NUM_FLOORS, "5.5 floors")

    assert result.needs_clarification is True
    assert result.value is None
    assert result.clarification_question == clarification_text


def test_parse_answer_non_positive_rejection_falls_back_when_llm_unreachable():
    extraction = _answer_json(value=-2.0, unit="inch")
    with patch(
        "app.common.llm_parser.llm_client.complete",
        side_effect=[extraction, LLMUnavailableError("no key")],
    ):
        result = parse_answer(BOREWELL_SIZE, "-2 inch")

    assert result.needs_clarification is True
    assert result.value is None
    assert "greater than zero" in result.clarification_question


def test_parse_answer_confirmation_message_absent_on_skip():
    fake_response = _answer_json(skipped=True)
    with patch("app.common.llm_parser.llm_client.complete", return_value=fake_response):
        result = parse_answer(MOTOR_POWER_HP, "skip")

    assert result.skipped is True
    assert result.confirmation_message is None


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
