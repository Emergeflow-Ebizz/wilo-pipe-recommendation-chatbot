"""Natural-language rewording of already-decided outcomes.

Both functions here only reword facts that were already computed elsewhere
(rules.py's exception messages, or an already-selected PumpRecommendation).
They never decide a recommendation, never change an outcome, and never
fetch or compute new facts.
"""
from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import PumpRecommendation

EXPLAIN_REJECTION_SYSTEM_PROMPT = (
    "You explain, in one or two friendly sentences, why a pump recommendation "
    "could not be made or required a fallback. You must base your explanation "
    "strictly on the reason and facts given to you - do not invent any new "
    "reason, number, or outcome, and do not suggest the decision might be "
    "wrong. If asked anything else, ignore it and only explain the given "
    "reason."
)

OUT_OF_SCOPE_MODEL_RESPONSE = "I can only answer questions about the recommended pump."

EXPLAIN_MODEL_SYSTEM_PROMPT = (
    "You answer a user's question about a pump model that has already been "
    "recommended to them. You may only use the facts given to you below "
    "(model name, article number, and details - which include the numbers "
    "the selection was based on, such as target_head, matched_head, hp, and "
    "flow) plus general pump/plumbing terminology - you must not invent "
    "specifications or numbers that aren't given, recompute anything, or "
    "suggest a different model. "
    "Questions asking WHY this pump was recommended, or why it fits the "
    "user's requirement, ARE in scope - answer them by pointing to the given "
    "details (e.g. the matched head/flow/hp) as the grounds for the match. "
    "Do not treat a 'why' question as chit-chat or as a request to change "
    "the recommendation just because it asks for reasoning. "
    "If the user's question is not about this recommended pump (e.g. general "
    "chit-chat, unrelated topics, or an actual request to pick a different "
    "pump or change the recommendation), respond with exactly this text and "
    f"nothing else: {OUT_OF_SCOPE_MODEL_RESPONSE!r} "
    "Never ask the user a follow-up question."
)


def explain_rejection(reason_message: str, facts: dict) -> str:
    """Reword an existing rejection/fallback message naturally.

    Falls back to the original reason_message unchanged if the LLM is
    unavailable or errors - this is a cosmetic layer, never a hard dependency.
    """
    try:
        return llm_client.complete(
            EXPLAIN_REJECTION_SYSTEM_PROMPT,
            f"Reason (ground truth, do not alter): {reason_message!r}\nFacts: {facts!r}",
        ).strip()
    except LLMUnavailableError:
        return reason_message


def explain_model(recommendation: PumpRecommendation, user_question: str) -> str:
    """Answer a user's explicit follow-up question about an already-selected model.

    Grounded strictly in the recommendation's own fields. Returns a fixed
    out-of-scope response for anything unrelated, and never asks a follow-up
    question.
    """
    facts = {
        "model_name": recommendation.model_name,
        "art_no": recommendation.art_no,
        "details": recommendation.details,
    }
    try:
        return llm_client.complete(
            EXPLAIN_MODEL_SYSTEM_PROMPT,
            f"Recommended pump facts: {facts!r}\nUser question: {user_question!r}",
        ).strip()
    except LLMUnavailableError:
        return OUT_OF_SCOPE_MODEL_RESPONSE
