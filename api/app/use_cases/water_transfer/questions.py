from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="borewell_size",
        prompt="What is the borewell diameter? (mm or inches accepted)",
        unit="inch",
        allowed_units=["inch", "mm"],
        requires_stated_unit=True,
        domain_context=(
            "Determines pump casing compatibility - the pump must physically fit "
            "inside the borewell. Available pump sheets cover 4-10 inches "
            "(roughly 100-250mm); below 4 inches no pump fits, above 10 inches "
            "the user is asked to confirm using the largest available size. Most "
            "domestic borewells are 6 or 6.5 inches (150-165mm). Valid units are "
            "inch and mm - the user must state which one, this is never inferred "
            "from the number alone (e.g. a bare '6' is not assumed to mean inches "
            "just because that's a typical size). "
            "IF THE USER DOESN'T KNOW HOW TO FIND THIS: the diameter is set by the "
            "drilling/casing pipe used when the borewell was drilled. It's usually "
            "written on the drilling contractor's invoice or completion report, or "
            "stamped/printed on the casing pipe itself just above ground level. If "
            "they truly can't find it, suggest they measure the inner diameter of "
            "the casing pipe opening directly, or contact the driller who installed "
            "it - most residential borewells turn out to be 6 or 6.5 inches."
        ),
    ),
    Question(
        key="well_depth",
        prompt="What is the borewell depth? (meters or feet accepted)",
        unit="ft",
        allowed_units=["ft", "m"],
        requires_stated_unit=True,
        domain_context=(
            "Used to calculate the total head the pump must lift water against, "
            "together with num_floors. Valid units are ft and m - the user must "
            "state which one, this is never inferred from the number alone (e.g. "
            "a bare '150' is not assumed to mean feet just because that's a "
            "typical depth). "
            "IF THE USER DOESN'T KNOW HOW TO FIND THIS: it's usually recorded on "
            "the drilling contractor's completion report or invoice from when the "
            "borewell was drilled. If that's unavailable, suggest lowering a "
            "weighted tape measure or string down the borewell until it hits the "
            "bottom, or contacting the driller who installed it. Depths commonly "
            "range from 100-600 feet (30-180m) depending on the local water table."
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
            "set unit to 'hp'."
        ),
    ),
    Question(
        key="num_floors",
        prompt="To how many floors above ground level is the water to be delivered?",
        requires_integer=True,
        domain_context=(
            "Used with well_depth to calculate the total head the pump must "
            "overcome - each floor adds a fixed height. Zero is a valid answer "
            "meaning water is only needed at ground level. Must be a whole "
            "number - fractional floors are meaningless."
        ),
    ),
    Question(
        key="roof_tank_capacity",
        prompt=(
            "What is the capacity of the elevated tank, in liters? This enables "
            "an estimate of fill duration. (optional)"
        ),
        unit="litres",
        optional=True,
        allowed_units=["litres"],
        domain_context=(
            "Optional - only used to estimate how long the tank takes to fill, "
            "never affects pump selection itself. Always in litres - there is no "
            "other unit option in this application. Never ask the user what "
            "unit it's in; just extract the number and set unit to 'litres'."
        ),
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
