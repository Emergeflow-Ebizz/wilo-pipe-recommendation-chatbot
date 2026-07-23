from abc import ABC, abstractmethod

from app.common.schemas import PumpRecommendation, Question


class UseCase(ABC):
    slug: str
    questions: list[Question]

    @abstractmethod
    def select_pump(self, answers: dict) -> PumpRecommendation:
        ...
