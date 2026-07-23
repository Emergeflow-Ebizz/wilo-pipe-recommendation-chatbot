"""Free-text answer parsing.

These functions only extract structured values (a number + unit, or a yes/no)
from what the user typed. They never validate, normalize, or decide
accept/reject/fallback - that logic lives entirely in each use case's
rules.py and is untouched by anything here.
"""
import json

from app.common import llm_client
from app.common.llm_client import LLMUnavailableError
from app.common.schemas import ParsedAnswer, ParsedCategory, Question

def _parse_answer_schema(allowed_units: list[str] | None, other_question_keys: list[str]) -> dict:
    """Build the structured-output schema for one question.

    Constraining unit to the exact canonical strings this use case's
    normalize_*() functions accept (e.g. "ft"/"m", not "feet"/"meter")
    means the LLM can only ever return a unit rules.py already understands -
    it cannot produce a synonym that would fail normalization downstream.
    The enum covers this question's own units plus every other question's
    units, since a redirected answer's unit belongs to whichever question
    redirect_key names, not necessarily this one.

    redirect_key is constrained the same way, to the exact keys of the
    other questions in this use case's sequence - the LLM can only name a
    question that actually exists, never invent one.
    """
    combined_units: list[str] = list(allowed_units or [])
    for key in other_question_keys:
        for unit in QUESTION_ALLOWED_UNITS.get(key, []):
            if unit not in combined_units:
                combined_units.append(unit)

    unit_schema = {"type": ["string", "null"]}
    if combined_units:
        unit_schema["enum"] = [*combined_units, None]

    redirect_schema = {"type": ["string", "null"]}
    if other_question_keys:
        redirect_schema["enum"] = [*other_question_keys, None]

    return {
        "type": "object",
        "properties": {
            "value": {"type": ["number", "null"]},
            "unit": unit_schema,
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
            "redirect_key": redirect_schema,
            "gave_up": {"type": "boolean"},
        },
        "required": [
            "value", "unit", "needs_clarification", "clarification_question",
            "skipped", "redirect_key", "gave_up",
        ],
    }


# The exact canonical unit strings each question's normalize_*() function in
# its use case's rules.py accepts - keep in sync with those functions.
QUESTION_ALLOWED_UNITS: dict[str, list[str]] = {
    "borewell_size": ["inch", "mm"],
    "well_depth": ["ft", "m"],
    "tank_capacity": ["litres"],
    "roof_tank_capacity": ["litres"],
    "motor_power_hp": ["hp"],
}

# Questions with more than one valid unit require the user to state which
# one they mean - see the "unit required" flow in the system prompt below.
# Single-unit questions (litres-only tank capacity, hp-only motor power)
# never need this since there's nothing to disambiguate.
QUESTIONS_REQUIRING_STATED_UNIT: set[str] = {"borewell_size", "well_depth"}

# Questions with no unit at all whose value must be a whole number (e.g.
# num_floors - "3.5 floors" is meaningless, unlike a measurement that can
# have a fractional part). A decimal reply must be rejected as invalid, not
# silently truncated.
QUESTIONS_REQUIRING_INTEGER: set[str] = {"num_floors"}

# Extra domain context per question key. This is guidance only - it never
# changes what rules.py accepts or rejects.
QUESTION_UNIT_HINTS: dict[str, str] = {
    "borewell_size": (
        "Valid units are inch and mm - the user must state which one, this "
        "is never inferred from the number alone (e.g. a bare '6' is not "
        "assumed to mean inches just because that's a typical size)."
    ),
    "well_depth": (
        "Valid units are ft and m - the user must state which one, this is "
        "never inferred from the number alone (e.g. a bare '150' is not "
        "assumed to mean feet just because that's a typical depth)."
    ),
    "tank_capacity": (
        "Tank capacity is always in litres - there is no other unit option "
        "in this application. Never ask the user what unit it's in; just "
        "extract the number and set unit to 'litres'."
    ),
    "roof_tank_capacity": (
        "Roof tank capacity is always in litres - there is no other unit "
        "option in this application. Never ask the user what unit it's in; "
        "just extract the number and set unit to 'litres'."
    ),
    "motor_power_hp": (
        "Motor power is always in HP - there is no other unit option in "
        "this application. Never ask the user what unit it's in; just "
        "extract the number and set unit to 'hp'."
    ),
}

PARSE_ANSWER_SYSTEM_PROMPT = (
    "You extract a numeric value and its unit from a user's free-text reply "
    "to a specific question. You do not validate whether the value is "
    "acceptable for this business (e.g. whether a borewell size is in a "
    "supported range) - that is decided elsewhere. "
    "EXCEPTION FIRST, applies before anything else in this paragraph: if "
    "the question being asked is 'num_floors' (how many floors above "
    "ground/the reservoir), zero IS a valid, normal value meaning ground "
    "floor - never reject a zero for this specific question, only reject "
    "a genuinely negative number for it. "
    "For every OTHER question (borewell size, well depth, motor power, "
    "tank capacity), you must never silently accept, silently strip the "
    "sign of, or silently round up a non-positive number (zero or "
    "negative) - these physical quantities must be strictly greater than "
    "zero, and zero/negative are never valid regardless of range. If the "
    "user's reply contains a zero or negative number for one of these "
    "non-num_floors questions, do not return it as the value (do not strip "
    "a minus sign to make it positive, and do not return the number "
    "as-is): set needs_clarification to true, leave value and unit null, "
    "and ask for a valid value greater than zero, naming the number they "
    "gave so they know what was rejected (e.g. \"-50 isn't a valid well "
    "depth - depth can't be negative. What is the well depth?\", or \"0 "
    "isn't a valid borewell diameter - it must be greater than zero. What "
    "is the borewell diameter?\"). This overrides skip handling below - "
    "even on an optional question, a zero or negative number (for a "
    "non-num_floors question) is treated as an invalid value needing "
    "clarification, not a skip, since the user did attempt to give a "
    "value. You do not perform any unit conversion arithmetic yourself "
    "beyond identifying which unit the user meant. "
    "If this question is listed below as one that REQUIRES A WHOLE NUMBER, "
    "the value must be a whole number - if the user's reply is a non-whole "
    "number (e.g. '5.5'), do not round or truncate it: set "
    "needs_clarification to true, leave value null, and ask for a whole "
    "number, naming the number they gave (e.g. \"5.5 isn't a whole number - "
    "how many whole floors?\"). This question has no unit at all - never "
    "return or ask about a unit for it. "
    "If this question is listed below as one that REQUIRES A STATED UNIT, "
    "the user must explicitly say which unit their number is in - you must "
    "never infer the unit from the number's magnitude or typical values for "
    "this kind of question, even if one unit would seem obvious. How far "
    "along this question's unit-ask sequence you already are is given below "
    "as a count of prior unit-ask attempts - use it exactly as follows: "
    "(a) Count is 0 (never asked yet): if the user gave a number with no "
    "unit stated at all (e.g. just '150' or '6'), do not guess a unit - "
    "but DO still return that number in value (leave unit null), so the "
    "caller does not lose it while it goes and asks for the unit. Set "
    "needs_clarification to true and ask exactly this form of question, "
    "naming the question's own subject (not a generic word like 'that'): "
    "'What is the unit of <subject>?' - e.g. for well depth: 'What is the "
    "unit of well depth?'; for borewell size: 'What is the unit of "
    "borewell size?'. "
    "(b) Count is 1 (the plain question above was already asked once): if "
    "the user's current reply still doesn't state a concrete unit - "
    "including 'idk', 'not sure', 'I don't know', or similar - set "
    "needs_clarification to true, leave value and unit null (even if a "
    "previous value is given below), and reply with exactly: 'I would "
    "require the unit to recommend the right pump for you - you can enter "
    "it in any unit you know, and I'll convert it.' Do not repeat the "
    "plain question a second time; escalate to this explanation instead. "
    "(c) Count is 2 (that escalation was already given once): if the "
    "user's current reply STILL doesn't state a concrete unit, do not ask "
    "again in any form - set needs_clarification to false, gave_up to "
    "true, value and unit null, and leave clarification_question null; the "
    "caller will end the conversation for this question rather than ask "
    "again. "
    "At any count, if the user's reply (now or previously) DOES state a "
    "concrete unit - even alone, with no number, as a correction of a "
    "previous reply - accept it normally regardless of attempt count: "
    "combine it with whatever number is available (their own reply, or a "
    "previous value given below) and return that value/unit as a normal "
    "parsed answer, with needs_clarification and gave_up both false. "
    "None of this unit-required handling applies to an optional question "
    "where the user is choosing to skip rather than attempting to give a "
    "value at all - skip handling below still applies to actual "
    "skip-intent replies, and gave_up must stay false in that case too. "
    "If the question is marked optional and the user's reply indicates they "
    "don't have or don't want to give a value - including explicit 'skip', "
    "'no', 'not sure', 'don't know', or similar - set skipped to true and "
    "leave value/unit/needs_clarification/clarification_question at their "
    "default (null/false). Never ask a clarification question for an "
    "optional field the user is unsure about; skip it instead. "
    "If the question is NOT optional, skipped must stay false even if the "
    "user seems unsure - a required question cannot be skipped, so ask a "
    "clarification_question that helps them arrive at a value instead; do "
    "not offer or imply that skipping is an option. "
    "If the user's reply is genuinely ambiguous and skipping does not apply, "
    "set needs_clarification to true, leave value and unit null, and provide "
    "a short, specific clarification_question - do not guess a unit just to "
    "fill the field, and never fall back to a default unit as a substitute "
    "for genuine understanding of what the user meant. "
    "Only ask a clarification question when strictly necessary; never ask "
    "about anything other than the value/unit of this specific question. "
    "If a previous value/unit is given below, that is what was parsed and "
    "shown to the user for this same question in an earlier turn - the "
    "user's current reply may be correcting that unit rather than giving a "
    "full restated answer (e.g. after '150 ft' was recorded, the user might "
    "reply 'no it's meters' or just 'meter', with no number). When the "
    "current reply states only a different unit and no new number, keep "
    "the previous value and use the unit the user is now stating - the "
    "user's stated unit always wins over whatever was recorded before, "
    "without question. Only ask for clarification here if the reply "
    "corrects the unit but you cannot tell what value it should apply to. "
    "If a list of this use case's OTHER questions is given below, the user's "
    "reply might actually be correcting an answer they already gave to one "
    "of those, not answering the current question - e.g. the current "
    "question is motor power, but the user replies 'no 50 meter' or 'wait, "
    "well depth is actually 50 meters', clearly referring back to the well "
    "depth question rather than stating a motor power. "
    "CHECK FOR THIS FIRST, before applying any skip/clarification rule above: "
    "if the reply unambiguously refers to a different, specific question "
    "from that list (by its topic - a unit or term that belongs to that "
    "question, not just any off-topic remark), this is a redirect case and "
    "ONLY these fields matter - set redirect_key to that question's key, "
    "put the corrected numeric value in value and its unit in unit (both "
    "must be non-null - if you cannot determine a concrete value for the "
    "other question, this is not a valid redirect, so fall through to the "
    "rules below instead), and set BOTH needs_clarification and skipped to "
    "false. A leading 'no' in a redirect reply (e.g. 'no 50 meter') is the "
    "user rejecting your last guess for the OTHER question, not skipping "
    "the current one - do not let that 'no' trigger the skip rule above. "
    "redirect_key, skipped, and needs_clarification are mutually exclusive - "
    "exactly one of them applies to the current question (or none, if this "
    "is a normal parsed answer); never set more than one of "
    "redirect_key-is-non-null, skipped=true, needs_clarification=true at "
    "the same time. "
    "If the reply is ambiguous about which question it corrects, or doesn't "
    "clearly reference any other question, leave redirect_key null and "
    "handle the reply as an answer (or clarification/skip) for the current "
    "question as usual."
)


def parse_answer(
    question: Question,
    user_text: str,
    *,
    previous_value: float | None = None,
    previous_unit: str | None = None,
    other_questions: list[Question] = (),
    unit_ask_attempts: int = 0,
) -> ParsedAnswer:
    """Parse a free-text answer into a numeric value + unit for `question`.

    For questions in QUESTIONS_REQUIRING_STATED_UNIT, the LLM never infers
    the unit from magnitude - the user must state it explicitly. The
    resulting (value, unit) still flows through this use case's own
    normalize_*/rules.py logic unchanged.

    previous_value/previous_unit, when given, are the value/unit this
    function previously parsed for this same question - they let a bare
    unit correction from the user (e.g. "no it's meters") reuse the
    previously stated number instead of being treated as a fresh,
    number-less reply.

    unit_ask_attempts tracks how far along this question's unit-ask
    sequence the caller already is: 0 = never asked, 1 = the plain "What is
    the unit of X?" question was already asked once, 2 = the "I would
    require the unit..." escalation was already given once. At 2, a further
    non-answer sets gave_up=true instead of asking again - the caller
    should end the conversation for this question in that case rather than
    call parse_answer for it again.

    other_questions, when given, lets the LLM recognize a reply that's
    actually correcting an earlier answer rather than answering the current
    question - the caller is responsible for updating its own answers state
    and re-asking the current question when redirect_key comes back set.
    """
    hint = QUESTION_UNIT_HINTS.get(question.key, "")
    allowed_units = QUESTION_ALLOWED_UNITS.get(question.key)
    allowed_units_line = (
        f"Valid unit values for this question - unit must be exactly one of these "
        f"strings (or null): {allowed_units!r}\n"
        if allowed_units
        else ""
    )
    unit_required_line = (
        f"This question REQUIRES A STATED UNIT (see the unit-required rule "
        f"above) - never infer the unit from magnitude. Prior unit-ask "
        f"attempts so far for this question: {unit_ask_attempts!r}.\n"
        if question.key in QUESTIONS_REQUIRING_STATED_UNIT
        else ""
    )
    integer_required_line = (
        "This question REQUIRES A WHOLE NUMBER (see the whole-number rule "
        "above) and has no unit.\n"
        if question.key in QUESTIONS_REQUIRING_INTEGER
        else ""
    )
    previous_guess = (
        f"Your previous guess for this question: {previous_value!r} {previous_unit!r}\n"
        if previous_value is not None
        else ""
    )
    other_question_keys = [q.key for q in other_questions]
    other_questions_line = (
        "This use case's OTHER questions, in case the reply corrects one of "
        "these instead of answering the current question - each is "
        f"(key, prompt): {[(q.key, q.prompt) for q in other_questions]!r}\n"
        if other_questions
        else ""
    )
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"{allowed_units_line}"
        f"{unit_required_line}"
        f"{integer_required_line}"
        f"{hint}\n"
        f"{previous_guess}"
        f"{other_questions_line}"
        f"User's reply: {user_text!r}"
    )

    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_answer_schema(allowed_units, other_question_keys),
        )
        data = json.loads(raw)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError):
        if question.optional:
            return ParsedAnswer(skipped=True)
        return ParsedAnswer(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't understand that answer for \"{question.prompt}\". "
                "Could you rephrase it, including the unit if there is one?"
            ),
        )

    # Defensive: a question with exactly one valid unit (e.g. hp-only motor
    # power, litres-only tank capacity) never needs a unit-ask - that unit is
    # implicit. Don't rely solely on the model following the per-question
    # hint above: if it extracted a number but asked for the unit anyway (or
    # left unit null), force the single valid unit instead of surfacing a
    # spurious clarification. Skipped when this is a redirect - the parsed
    # value/unit then belong to whichever question redirect_key names, which
    # may have a different (or multi-option) unit set than this question.
    if (
        not data.get("redirect_key")
        and allowed_units
        and len(allowed_units) == 1
        and question.key not in QUESTIONS_REQUIRING_STATED_UNIT
    ):
        if data.get("value") is not None:
            data["unit"] = allowed_units[0]
            data["needs_clarification"] = False
            data["clarification_question"] = None

    # Defensive: a question requiring a whole number (e.g. num_floors) must
    # never accept a fractional value - don't rely solely on the model
    # following the whole-number instruction above. Skipped when this is a
    # redirect, since the parsed value then belongs to whichever question
    # redirect_key names, which may be a different, fractional-allowed one.
    if (
        not data.get("redirect_key")
        and question.key in QUESTIONS_REQUIRING_INTEGER
        and data.get("value") is not None
        and data["value"] != int(data["value"])
    ):
        rejected_number = data["value"]
        data["value"] = None
        data["unit"] = None
        data["skipped"] = False
        data["needs_clarification"] = True
        data["clarification_question"] = (
            f"{rejected_number!r} isn't a whole number - could you give a "
            f"whole number for \"{question.prompt}\"?"
        )

    # Defensive normalization: redirect_key/skipped/needs_clarification are
    # meant to be mutually exclusive (see the system prompt), and a redirect
    # is only usable if it carries a concrete value. If the model ever
    # returns an inconsistent combination anyway, don't let a malformed
    # redirect (or a redirect tangled up with skip/clarification) reach the
    # caller - fall back to asking for clarification on the current
    # question instead of silently corrupting either question's answer.
    if data.get("redirect_key") and data.get("value") is None:
        data["redirect_key"] = None
        data["needs_clarification"] = True
        data["skipped"] = False
        data.setdefault("clarification_question", None)
        if not data["clarification_question"]:
            data["clarification_question"] = (
                f"Could you clarify that answer for \"{question.prompt}\"?"
            )
    elif data.get("redirect_key"):
        data["needs_clarification"] = False
        data["skipped"] = False

    # Defensive: these are physical quantities that must be strictly
    # positive - zero is just as meaningless as negative for a borewell
    # diameter, well depth, motor power, or tank capacity (unlike
    # num_floors, where 0 legitimately means ground floor). Don't rely
    # solely on the model following the negative-value instruction above -
    # if a non-positive value ever comes back (for the current question or
    # a redirected one), force clarification instead of silently accepting
    # or silently stripping the sign.
    rejected_value = data.get("value")
    target_key = data.get("redirect_key") or question.key
    if rejected_value is not None and rejected_value <= 0 and target_key not in QUESTIONS_REQUIRING_INTEGER:
        target_prompt = question.prompt
        if data.get("redirect_key"):
            target_prompt = next(
                (q.prompt for q in other_questions if q.key == data["redirect_key"]),
                target_prompt,
            )
        data["value"] = None
        data["unit"] = None
        data["redirect_key"] = None
        data["skipped"] = False
        data["needs_clarification"] = True
        reason = "it can't be negative" if rejected_value < 0 else "it must be greater than zero"
        data["clarification_question"] = (
            f"{rejected_value!r} isn't a valid value for \"{target_prompt}\" - "
            f"{reason}. Could you give a valid value?"
        )
        data["gave_up"] = False

    # Defensive: after the plain unit-ask and the escalation have both
    # already been given (attempts >= 2) and the reply still has no concrete
    # unit, the model should stop asking - don't rely solely on it following
    # that instruction. Only forces this when the model still left the
    # question genuinely unanswered (no value); a value it did manage to
    # extract this turn (e.g. the user finally stated a unit) always wins.
    if (
        question.key in QUESTIONS_REQUIRING_STATED_UNIT
        and unit_ask_attempts >= 2
        and data.get("value") is None
        and not data.get("redirect_key")
        and not data.get("skipped")
    ):
        data["gave_up"] = True
        data["needs_clarification"] = False
        data["clarification_question"] = None
    else:
        data.setdefault("gave_up", False)

    return ParsedAnswer(**data)


def _parse_category_schema(valid_categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": ["string", "null"], "enum": [*valid_categories, None]},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "skipped": {"type": "boolean"},
        },
        "required": ["category", "needs_clarification", "clarification_question", "skipped"],
    }


PARSE_CATEGORY_SYSTEM_PROMPT = (
    "You determine which one of a fixed set of categories the user's "
    "free-text reply means, for a specific question. The valid categories "
    "are given to you exactly - you must return one of those exact strings "
    "(or null), never a synonym, paraphrase, or a category not in the list. "
    "Use natural-language understanding, not just literal keyword matching "
    "- e.g. if the categories are 'inside'/'outside' and the user replies "
    "'it's kept outdoors' or 'in the yard', that means 'outside'; if they "
    "reply 'in the pump room' or 'indoor', that means 'inside'. "
    "If the question is marked optional and the user's reply indicates they "
    "don't have or don't want to choose - 'skip', 'not sure', 'no', 'don't "
    "know', or similar - set skipped to true and leave category/"
    "needs_clarification/clarification_question at their default. Never do "
    "this for a non-optional question - ask for clarification instead. "
    "If the reply genuinely doesn't map to any valid category, set "
    "needs_clarification to true, leave category null, and ask a short "
    "clarification_question naming the valid options - do not guess a "
    "category just to fill the field."
)


def parse_category(
    question: Question,
    user_text: str,
    valid_categories: list[str],
) -> ParsedCategory:
    """Parse a free-text answer into one of `valid_categories` for `question`.

    Used for fixed-choice questions (e.g. inside/outside,
    horizontal/vertical) so natural phrasing ("it's kept outdoors") maps to
    the exact category string rules.py expects, instead of requiring the
    user to type one of the literal option words.
    """
    user_prompt = (
        f"Question asked: {question.prompt!r}\n"
        f"Optional: {question.optional!r}\n"
        f"Valid categories: {valid_categories!r}\n"
        f"User's reply: {user_text!r}"
    )

    try:
        raw = llm_client.complete(
            PARSE_CATEGORY_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_category_schema(valid_categories),
        )
        data = json.loads(raw)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError):
        if question.optional:
            return ParsedCategory(skipped=True)
        return ParsedCategory(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't understand that answer for \"{question.prompt}\". "
                f"Please choose one of: {', '.join(valid_categories)}."
            ),
        )

    return ParsedCategory(**data)


PARSE_YES_NO_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": ["boolean", "null"]},
        "needs_clarification": {"type": "boolean"},
    },
    "required": ["confirmed", "needs_clarification"],
}

PARSE_YES_NO_SYSTEM_PROMPT = (
    "You determine whether a user's free-text reply is an affirmative "
    "confirmation (yes) or a negative one (no) to the previous question. "
    "If the reply is genuinely ambiguous, set needs_clarification to true "
    "and leave confirmed null - do not guess."
)


class AmbiguousConfirmationError(Exception):
    """Raised when a yes/no reply can't be confidently interpreted."""


def parse_yes_no(user_text: str) -> bool:
    """Parse a free-text confirmation reply into a boolean.

    Raises AmbiguousConfirmationError instead of guessing when the LLM
    can't confidently tell yes from no.
    """
    try:
        raw = llm_client.complete(
            PARSE_YES_NO_SYSTEM_PROMPT, f"User's reply: {user_text!r}", json_schema=PARSE_YES_NO_SCHEMA
        )
        data = json.loads(raw)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError) as e:
        raise AmbiguousConfirmationError(
            f"Could not confidently interpret {user_text!r} as yes or no."
        ) from e

    if data.get("needs_clarification") or data.get("confirmed") is None:
        raise AmbiguousConfirmationError(
            f"Could not confidently interpret {user_text!r} as yes or no."
        )
    return bool(data["confirmed"])
