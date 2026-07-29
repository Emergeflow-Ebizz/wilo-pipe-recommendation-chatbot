from app.common.schemas import Question

QUESTIONS: list[Question] = [
    Question(
        key="num_floors",
        prompt="How many floors does the building have?",
        requires_integer=True,
        min_value=1,
        domain_context=(
            "Used to calculate the building height the pump must deliver "
            "pressure to - each floor adds a fixed height. Also used with "
            "bathrooms_per_floor to calculate total required flow. Must be "
            "at least 1 floor - fractional floors are meaningless."
        ),
    ),
    Question(
        key="bathrooms_per_floor",
        prompt="How many bathrooms are there per floor?",
        requires_integer=True,
        min_value=1,
        domain_context=(
            "Used with num_floors to calculate total required flow - each "
            "bathroom contributes a fixed flow rate at 60% utilisation. Must "
            "be at least 1 - fractional bathrooms are meaningless."
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
