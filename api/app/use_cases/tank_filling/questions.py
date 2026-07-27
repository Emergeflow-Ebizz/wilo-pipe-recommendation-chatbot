from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="inside_or_outside",
        prompt=(
            "Will the pump be installed submerged inside the reservoir, or "
            "externally at ground level (e.g. in a pump room)?"
        ),
        domain_context=(
            "Determines whether a submersible or a surface (ground-level) pump "
            "model is required - this is a hard selection criterion, not a "
            "preference."
        ),
    ),
    Question(
        key="tank_capacity",
        prompt="What is the capacity of the receiving tank, in liters? (optional)",
        unit="litres",
        optional=True,
        allowed_units=["litres"],
        domain_context=(
            "Optional - only used to estimate fill duration, never affects pump "
            "selection itself. Always in litres - there is no other unit option "
            "in this application. Never ask the user what unit it's in; just "
            "extract the number and set unit to 'litres'."
        ),
    ),
    Question(
        key="num_floors",
        prompt="To how many floors above the reservoir is the water to be delivered?",
        requires_integer=True,
        domain_context=(
            "Used to calculate the total head the pump must overcome - each "
            "floor adds a fixed height. Zero is a valid answer meaning water is "
            "only needed at ground level. Must be a whole number - fractional "
            "floors are meaningless."
        ),
    ),
    Question(
        key="motor_power_hp",
        prompt="Do you have a required motor power rating (HP)? (optional)",
        optional=True,
        allowed_units=["hp"],
        domain_context=(
            "Optional constraint on which pump model is selected. Motor power is "
            "always in HP - there is no other unit option in this application. "
            "Never ask the user what unit it's in; just extract the number and "
            "set unit to 'hp'."
        ),
    ),
]

HORIZONTAL_OR_VERTICAL_QUESTION = Question(
    key="horizontal_or_vertical",
    prompt="Is your tank Horizontal or vertical (optional)?",
    optional=True,
    domain_context=(
        "Optional - only relevant for outside/ground-level installations, "
        "affects which pump orientation model is selected."
    ),
)


def next_question(answers: dict) -> Question | None:
    """Return the next question to ask given answers collected so far.

    horizontal_or_vertical is not a fixed-position question - it only exists
    as a follow-up asked right after inside_or_outside, and only when
    inside_or_outside == "inside".
    """
    if "inside_or_outside" not in answers:
        return QUESTIONS[0]

    if answers["inside_or_outside"] == "inside" and "horizontal_or_vertical" not in answers:
        return HORIZONTAL_OR_VERTICAL_QUESTION

    for question in QUESTIONS:
        if question.key in answers:
            continue
        return question
    return None
