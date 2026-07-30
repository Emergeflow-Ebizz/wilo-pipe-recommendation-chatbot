from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="depth_of_pit",
        prompt="What is the depth of the pit/sump? (meters or feet accepted)",
        unit="ft",
        allowed_units=["ft", "m"],
        requires_stated_unit=True,
        domain_context=(
            "Used to calculate the total head the dewatering pump must lift "
            "water against. Valid units are ft and m - the user must state "
            "which one, this is never inferred from the number alone (e.g. a "
            "bare '15' is not assumed to mean feet just because that's a "
            "typical depth)."
        ),
    ),
    Question(
        key="motor_power_hp",
        prompt="Do you have a required motor power rating (HP)? (optional)",
        unit="hp",
        optional=True,
        allowed_units=["hp"],
        domain_context=(
            "Optional constraint on which pump model is selected. Motor power is "
            "always in HP - there is no other unit option in this application. "
            "Never ask the user what unit it's in; just extract the number and "
            "set unit to 'hp'. If not given, the lowest-HP model that reaches "
            "the required head is selected."
        ),
    ),
]


def next_question(answers: dict) -> Question | None:
    """Return the next question to ask given answers collected so far."""
    for question in QUESTIONS:
        if question.key in answers:
            continue
        return question
    return None
