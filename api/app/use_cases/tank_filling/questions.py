from app.common.schemas import Question

QUESTIONS: list[Question] = [
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

INSIDE_OR_OUTSIDE_QUESTION = Question(
    key="inside_or_outside",
    prompt="Pump is Inside the tank or Outside the tank",
    domain_context=(
        "Determines whether a submersible or a surface (ground-level) pump "
        "model is required - this is a hard selection criterion, not a "
        "preference."
    ),
)

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

    inside_or_outside is asked last, after tank_capacity/num_floors/
    motor_power_hp. horizontal_or_vertical is a follow-up asked right after
    inside_or_outside, only when inside_or_outside == "inside".
    """
    for question in QUESTIONS:
        if question.key in answers:
            continue
        return question

    if "inside_or_outside" not in answers:
        return INSIDE_OR_OUTSIDE_QUESTION

    if answers["inside_or_outside"] == "inside" and "horizontal_or_vertical" not in answers:
        return HORIZONTAL_OR_VERTICAL_QUESTION

    return None
