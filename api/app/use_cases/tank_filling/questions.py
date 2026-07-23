from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="inside_or_outside",
        prompt=(
            "Will the pump be installed submerged inside the reservoir, or "
            "externally at ground level (e.g. in a pump room)?"
        ),
    ),
    Question(key="tank_capacity", prompt="What is the capacity of the receiving tank, in liters? (optional)", unit="litres", optional=True),
    Question(key="num_floors", prompt="To how many floors above the reservoir is the water to be delivered?"),
    Question(key="motor_power_hp", prompt="Do you have a required motor power rating (HP)? (optional)", optional=True),
]

HORIZONTAL_OR_VERTICAL_QUESTION = Question(key="horizontal_or_vertical", prompt="Is your tank Horizontal or vertical (optional)?", optional=True)


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
