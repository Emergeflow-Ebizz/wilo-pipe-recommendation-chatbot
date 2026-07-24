"""Free-text answer parsing.

These functions only extract structured values (a number + unit, or a yes/no)
from what the user typed. They never validate, normalize, or decide
accept/reject/fallback - that logic lives entirely in each use case's
rules.py and is untouched by anything here.
"""
import json
import re

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

    # No enum here on purpose: the model is asked to normalize noisy input
    # (typos, filler like "inchhhhh", casing) into a canonical unit itself,
    # but forcing an enum on a tool-use call makes the provider reject the
    # whole response when it can't map cleanly - safer to accept any string
    # and let _normalize_unit() below fuzzy-correct it on our side.
    unit_schema = {"type": ["string", "null"]}

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

def _generate_clarification_question(
    question_key: str,
    allowed_units: list[str] | None,
    unit_ask_attempts: int,
    extracted_value: float | None,
    extracted_unit: str | None,
) -> str:
    """Generate a natural clarification question for pump selection."""
    units_str = ", ".join(allowed_units) if allowed_units else "the available units"
    subject = question_key.replace('_', ' ')

    prompt = (
        f"User is being asked about: {subject}. "
        f"Valid units: {units_str}. "
        f"They've been asked {unit_ask_attempts + 1} time(s). "
        f"Ask them naturally. Only about this specific question for pump selection. "
        f"Output only the question."
    )

    try:
        response = llm_client.complete(
            "Generate a follow-up question for pump selection. Keep it natural and focused.",
            prompt,
            temperature=1.0  # High temp for natural variety
        ).strip()
        # Clean up markdown
        response = "\n".join(line.strip() for line in response.split("\n") if line.strip() and not line.startswith("#"))
        return response.strip() if response else f"Please provide {subject}."
    except LLMUnavailableError:
        return f"Please provide {subject}."


def _normalize_unit(raw_unit: str | None, allowed_units: list[str] | None) -> str | None:
    """Normalize unit text to match allowed units using fuzzy matching.

    Handles typos and variations by checking substring containment. Returns
    the matching canonical unit, or None if no match found.
    """
    if not raw_unit or not allowed_units:
        return raw_unit
    cleaned = raw_unit.strip().lower()
    if cleaned in allowed_units:
        return cleaned
    for candidate in allowed_units:
        if candidate in cleaned or cleaned in candidate:
            return candidate
    return raw_unit


PARSE_ANSWER_SYSTEM_PROMPT = (
    "You extract a numeric value and its unit from a user's free-text reply "
    "to a specific question. Return only what the user actually said - do not "
    "validate, do not decide whether to ask follow-up questions, just extract. "
    "The user's text may be noisy (typos, repeated letters, filler: 'inchhhhh', "
    "'MM', 'i guess 5 inch', 'idkkk', 'fiveeeee'). Convert spelled-out numbers "
    "to digits (e.g. 'five' -> 5, 'twenty three' -> 23). Normalize the unit to "
    "its clean canonical form (e.g. 'inchhhhh' -> 'inch', 'MM' -> 'mm'). If the "
    "user said a number with no unit, return the number in value and leave unit "
    "null - the caller will decide what to ask next. "
    "EXCEPTION: 'num_floors' (floors above ground) allows zero as a valid value "
    "meaning ground floor. For all other numeric questions (borewell size, well "
    "depth, motor power, tank capacity), reject any zero or negative number - set "
    "needs_clarification=true, value/unit null, and ask for a value > zero. "
    "WHOLE NUMBER: If the question requires a whole number (num_floors), reject "
    "any non-whole reply (e.g. '5.5') - set needs_clarification=true, value null, "
    "ask for a whole number. "
    "SKIP: If optional and the user says skip/no/idk/don't know/etc, set "
    "skipped=true, leave value/unit/needs_clarification/clarification_question null. "
    "If NOT optional, never skip - ask for clarification instead. "
    "REDIRECT: If the user's reply clearly corrects an EARLIER answer to a "
    "different question (e.g. current question is motor power but user says "
    "'well depth is 50 meters'), set redirect_key to that question's key, put the "
    "corrected value/unit in value/unit, set needs_clarification=false, skipped=false. "
    "Only if you can determine both a concrete value AND its unit for the other question. "
    "Otherwise treat it as a clarification for the current question. "
    "PREVIOUS VALUE: If a previous value/unit was recorded for this same question, "
    "treat it as still valid unless the user's current reply gives a new, different "
    "number - keep carrying it forward turn after turn. If the current reply states "
    "only a unit (e.g. 'no it's meters') or is unrelated/confused (e.g. 'idk', 'how "
    "would I know'), still return the previously recorded value in value - do not "
    "null it out just because this particular reply didn't repeat the number. Only "
    "replace it if the user gives an actual new number this turn. The user's stated "
    "unit always wins over any previously recorded unit. "
    "AMBIGUOUS: If genuinely unclear, set needs_clarification=true, value/unit null, "
    "and ask a short clarification_question. "
    "Never ask about anything other than THIS question's value/unit. "
    "redirect_key, skipped, and needs_clarification are mutually exclusive."
)


def _try_rule_based_parse(user_text: str, allowed_units: list[str] | None, question_key: str, previous_value: float | None = None) -> dict | None:
	"""Attempt to extract value + unit using regex/pattern matching.

	Returns a dict matching the LLM response schema if a clear match is found,
	otherwise None to fall back to LLM parsing.
	"""
	user_text = user_text.strip()
	if not user_text:
		return None

	if allowed_units is None:
		match = re.match(r'^\s*([+-]?\d+(?:\.\d+)?)\s*$', user_text)
		if not match:
			return None
		value_str = match.group(1)
		value = float(value_str)
		if question_key in QUESTIONS_REQUIRING_INTEGER and value != int(value):
			return None
		return {
			"value": value,
			"unit": None,
			"needs_clarification": False,
			"clarification_question": None,
			"skipped": False,
			"redirect_key": None,
			"gave_up": False,
		}

	unit_pattern = "|".join(re.escape(unit) for unit in allowed_units)
	pattern = rf'^\s*([+-]?\d+(?:\.\d+)?)\s*({unit_pattern})\s*$'
	match = re.match(pattern, user_text, re.IGNORECASE)

	if not match:
		# Check if it's just a unit correction (no number, but a valid unit)
		cleaned = user_text.lower()
		for unit in allowed_units:
			if cleaned == unit or cleaned in unit or unit in cleaned:
				if previous_value is not None:
					return {
						"value": previous_value,
						"unit": unit,
						"needs_clarification": False,
						"clarification_question": None,
						"skipped": False,
						"redirect_key": None,
						"gave_up": False,
					}
		return None

	value_str, unit_str = match.groups()
	value = float(value_str)
	unit = unit_str.lower()

	if unit not in allowed_units:
		return None

	if question_key in QUESTIONS_REQUIRING_INTEGER and value != int(value):
		return None

	return {
		"value": value,
		"unit": unit,
		"needs_clarification": False,
		"clarification_question": None,
		"skipped": False,
		"redirect_key": None,
		"gave_up": False,
	}


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
        f"User's reply: {user_text!r}\n"
        f"Track what's NEW: compare user's current reply against previous answer. "
        f"If they previously said a number but no unit, and now they say a unit keyword, "
        f"extract that unit. If they say both, extract both. Always look for evidence "
        f"of what the user is stating, even in typos or casual language."
    )

    try:
        raw = llm_client.complete(
            PARSE_ANSWER_SYSTEM_PROMPT,
            user_prompt,
            json_schema=_parse_answer_schema(allowed_units, other_question_keys),
        )
        data = json.loads(raw)
        data["unit"] = _normalize_unit(data.get("unit"), allowed_units)
    except (LLMUnavailableError, json.JSONDecodeError, ValueError):
        rule_based = _try_rule_based_parse(user_text, allowed_units, question.key, previous_value)
        if rule_based is not None:
            data = rule_based
        else:
            if question.optional:
                return ParsedAnswer(skipped=True)
            return ParsedAnswer(
                needs_clarification=True,
                clarification_question=(
                    f"I couldn't understand that answer for \"{question.prompt}\". "
                    "Could you rephrase it, including the unit if there is one?"
                ),
            )

    # Defensive: don't let an already-recorded value get silently dropped just
    # because this turn's reply didn't repeat it (e.g. "idk", "how would I
    # know?", a bare unit correction). The prompt asks the model to carry
    # previous_value forward on its own, but that's not reliable enough to
    # trust alone - if the model came back with value=None while we were
    # given a previous_value, and this isn't a redirect/skip, restore it.
    if (
        not data.get("redirect_key")
        and not data.get("skipped")
        and data.get("value") is None
        and previous_value is not None
    ):
        data["value"] = previous_value

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

    # Clarification question: if we're asking for missing value/unit, generate
    # the clarification question with high temperature so the wording varies.
    # The LLM decides what's actually missing based on what was extracted.
    if (
        not data.get("redirect_key")
        and not data.get("skipped")
        and question.key in QUESTIONS_REQUIRING_STATED_UNIT
        and data.get("needs_clarification")
        and unit_ask_attempts < 2
    ):
        data["clarification_question"] = _generate_clarification_question(
            question.key,
            allowed_units,
            unit_ask_attempts,
            data.get("value"),
            data.get("unit"),
        )

    # Give-up threshold: if we're at attempt 2+ and still missing required info,
    # stop and give up. Generate a final message via LLM.
    if (
        not data.get("redirect_key")
        and not data.get("skipped")
        and question.key in QUESTIONS_REQUIRING_STATED_UNIT
        and data.get("unit") is None
        and unit_ask_attempts >= 2
    ):
        data["value"] = None
        data["needs_clarification"] = False
        data["gave_up"] = True
        # Generate the "cannot recommend" message via LLM
        try:
            data["clarification_question"] = llm_client.complete(
                "You generate brief, empathetic messages. Output only the message itself, nothing else.",
                f"The user couldn't provide the {question.key.replace('_', ' ')} information after being asked twice. Generate a brief, friendly message saying we cannot recommend a pump model without this information.",
                temperature=1.0
            ).strip()
        except LLMUnavailableError:
            data["clarification_question"] = "We cannot recommend you a model because of missing information."

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
