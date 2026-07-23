from dataclasses import dataclass, field


@dataclass
class ChatSession:
    session_id: str
    use_case_slug: str
    answers: dict = field(default_factory=dict)
    next_question_index: int = 0
