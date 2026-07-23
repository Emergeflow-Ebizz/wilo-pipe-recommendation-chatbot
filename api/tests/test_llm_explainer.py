"""Tests for llm_explainer, mocking the LLM client so no real API key is needed."""
from unittest.mock import patch

from app.common.llm_client import LLMUnavailableError
from app.common.llm_explainer import OUT_OF_SCOPE_MODEL_RESPONSE, explain_model, explain_rejection
from app.common.schemas import PumpRecommendation


def test_explain_rejection_falls_back_to_original_message_when_llm_unavailable():
    reason = "No suitable pump is available for a borewell smaller than 4 inch."
    with patch("app.common.llm_explainer.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = explain_rejection(reason, {"borewell_size": 2, "min_required": 4})

    assert result == reason


def test_explain_rejection_uses_llm_output_when_available():
    reason = "No suitable pump is available for a borewell smaller than 4 inch."
    with patch("app.common.llm_explainer.llm_client.complete", return_value="Sorry, that borewell is too small."):
        result = explain_rejection(reason, {"borewell_size": 2, "min_required": 4})

    assert result == "Sorry, that borewell is too small."


def test_explain_model_falls_back_to_out_of_scope_when_llm_unavailable():
    recommendation = PumpRecommendation(model_name="WBW-3-A", art_no=101, details={"hp": 1.0, "flow": 50})
    with patch("app.common.llm_explainer.llm_client.complete", side_effect=LLMUnavailableError("no key")):
        result = explain_model(recommendation, "why this model?")

    assert result == OUT_OF_SCOPE_MODEL_RESPONSE
