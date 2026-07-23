from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(key="borewell_size", prompt="What is the borewell diameter? (mm or inches accepted)", unit="inch"),
    Question(key="well_depth", prompt="What is the borewell depth? (meters or feet accepted)", unit="ft"),
    Question(key="motor_power_hp", prompt="Do you have a required motor power rating (HP)? (optional)", unit="hp", optional=True),
    Question(key="num_floors", prompt="To how many floors above ground level is the water to be delivered?"),
    Question(
        key="roof_tank_capacity",
        prompt=(
            "What is the capacity of the elevated tank, in liters? This enables "
            "an estimate of fill duration. (optional)"
        ),
        unit="litres",
        optional=True,
    ),
]


def next_question(answers: dict) -> Question | None:
    """Return the next question to ask given answers collected so far.

    Skips roof_tank_capacity when num_floors is 0 - there's no roof tank
    to fill if the pump isn't feeding any floor.
    """
    for question in QUESTIONS:
        if question.key in answers:
            continue
        if question.key == "roof_tank_capacity" and answers.get("num_floors") == 0:
            continue
        return question
    return None
