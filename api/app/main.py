import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.common import llm_explainer, llm_parser
from app.common.schemas import (
    DewateringRequest,
    ParsedAnswer,
    ParsedCategory,
    PressureBoostingRequest,
    PumpRecommendation,
    Question,
    SendPumpDataRequest,
    TankFillingRequest,
    WaterTransferRequest,
)
from app.use_cases.dewatering.questions import QUESTIONS as DEWATERING_QUESTIONS
from app.use_cases.dewatering.questions import next_question as dewatering_next_question
from app.use_cases.dewatering.rules import (
    DewateringUseCase,
    NoDewateringMatchError,
    calculate_head as dewatering_calculate_head,
    normalize_depth_of_pit,
)
from app.use_cases.pressure_boosting.questions import QUESTIONS as PRESSURE_BOOSTING_QUESTIONS
from app.use_cases.pressure_boosting.questions import next_question as pressure_boosting_next_question
from app.use_cases.pressure_boosting.rules import (
    NoPressureBoostingMatchError,
    PressureBoostingUseCase,
    calculate_head as pressure_boosting_calculate_head,
)
from app.use_cases.tank_filling.questions import HORIZONTAL_OR_VERTICAL_QUESTION
from app.use_cases.tank_filling.questions import INSIDE_OR_OUTSIDE_QUESTION
from app.use_cases.tank_filling.questions import QUESTIONS as TANK_FILLING_QUESTIONS
from app.use_cases.tank_filling.questions import next_question as tank_filling_next_question
from app.use_cases.water_transfer.questions import DELIVERY_TYPE_QUESTION
from app.use_cases.tank_filling.rules import NoTankFillingMatchError, TankFillingUseCase
from app.use_cases.water_transfer.questions import QUESTIONS as WATER_TRANSFER_QUESTIONS
from app.use_cases.water_transfer.questions import next_question as water_transfer_next_question
from app.use_cases.water_transfer.rules import (
    BorewellOversizeConfirmationRequired,
    BorewellTooSmallError,
    MAX_BOREWELL_SIZE,
    MIN_BOREWELL_SIZE,
    NoModelAvailableError,
    OVERSIZE_DECLINE_MESSAGE,
    WaterTransferUseCase,
    calculate_head as water_transfer_calculate_head,
    normalize_well_depth,
)
from app.common.units import m_to_ft
from app.use_cases.tank_filling.rules import calculate_head as tank_filling_calculate_head

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

USE_CASES = {
    uc.slug: uc
    for uc in (
        WaterTransferUseCase(),
        TankFillingUseCase(),
        PressureBoostingUseCase(),
        DewateringUseCase(),
    )
}

NEXT_QUESTION_FNS = {
    "water_transfer": water_transfer_next_question,
    "tank_filling": tank_filling_next_question,
    "pressure_boosting": pressure_boosting_next_question,
    "dewatering": dewatering_next_question,
}

QUESTIONS_BY_SLUG = {
    "water_transfer": {q.key: q for q in WATER_TRANSFER_QUESTIONS},
    "tank_filling": {q.key: q for q in TANK_FILLING_QUESTIONS},
    "pressure_boosting": {q.key: q for q in PRESSURE_BOOSTING_QUESTIONS},
    "dewatering": {q.key: q for q in DEWATERING_QUESTIONS},
}

# Fixed-choice questions whose answer must be one of a small, exact set of
# strings that rules.py compares against literally - not free numeric input.
# Maps question_key -> (Question, valid category strings).
CATEGORY_QUESTIONS_BY_SLUG: dict[str, dict[str, tuple[Question, list[str]]]] = {
    "water_transfer": {
        "delivery_type": (DELIVERY_TYPE_QUESTION, ["ground_floor", "elevated_tank"]),
    },
    "tank_filling": {
        "inside_or_outside": (INSIDE_OR_OUTSIDE_QUESTION, ["inside", "outside"]),
        "horizontal_or_vertical": (HORIZONTAL_OR_VERTICAL_QUESTION, ["horizontal", "vertical"]),
    },
}


def _explain(reason_message: str, facts: dict) -> str:
    """Reword a rejection/fallback message; falls back to the raw message on any error."""
    try:
        return llm_explainer.explain_rejection(reason_message, facts)
    except Exception:
        return reason_message


class AnswerRequest(BaseModel):
    question_key: str
    user_text: str
    previous_value: float | None = None
    previous_unit: str | None = None
    clarification_attempts: int = 0
    # TODO(frontend): drop once static/app.js sends clarification_attempts
    # instead of the old unit_ask_attempts name. Until then this silently
    # falling back to 0 on every request would mean the give-up mechanic in
    # llm_parser.parse_answer could never fire in production.
    unit_ask_attempts: int | None = None


@app.post("/{use_case_slug}/answer", response_model=ParsedAnswer)
def parse_free_text_answer(use_case_slug: str, request: AnswerRequest) -> ParsedAnswer:
    questions = QUESTIONS_BY_SLUG.get(use_case_slug)
    if questions is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {use_case_slug}")
    question = questions.get(request.question_key)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Unknown question: {request.question_key}")
    other_questions = [q for key, q in questions.items() if key != request.question_key]
    clarification_attempts = (
        request.unit_ask_attempts if request.unit_ask_attempts is not None else request.clarification_attempts
    )
    return llm_parser.parse_answer(
        question,
        request.user_text,
        previous_value=request.previous_value,
        previous_unit=request.previous_unit,
        other_questions=other_questions,
        clarification_attempts=clarification_attempts,
    )


class CategoryAnswerRequest(BaseModel):
    question_key: str
    user_text: str


@app.post("/{use_case_slug}/answer_category", response_model=ParsedCategory)
def parse_category_answer(use_case_slug: str, request: CategoryAnswerRequest) -> ParsedCategory:
    category_questions = CATEGORY_QUESTIONS_BY_SLUG.get(use_case_slug, {})
    entry = category_questions.get(request.question_key)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown categorical question for {use_case_slug}: {request.question_key}",
        )
    question, valid_categories = entry
    return llm_parser.parse_category(question, request.user_text, valid_categories)


class ExplainModelRequest(BaseModel):
    recommendation: PumpRecommendation
    user_question: str


class ExplainModelResponse(BaseModel):
    answer: str


@app.post("/explain_model", response_model=ExplainModelResponse)
def explain_model(request: ExplainModelRequest) -> ExplainModelResponse:
    return ExplainModelResponse(
        answer=llm_explainer.explain_model(request.recommendation, request.user_question)
    )


class NextQuestionRequest(BaseModel):
    answers: dict = {}


class NextQuestionResponse(BaseModel):
    question: Question | None = None


@app.post("/{use_case_slug}/next_question", response_model=NextQuestionResponse)
def get_next_question(use_case_slug: str, request: NextQuestionRequest) -> NextQuestionResponse:
    next_question_fn = NEXT_QUESTION_FNS.get(use_case_slug)
    if next_question_fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown use case: {use_case_slug}")
    return NextQuestionResponse(question=next_question_fn(request.answers))


class WaterTransferResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/water_transfer/recommend", response_model=WaterTransferResponse)
def water_transfer_recommend(request: WaterTransferRequest) -> WaterTransferResponse:
    resolved_num_floors = 0 if request.delivery_type == "ground_floor" else request.num_floors

    answers = {
        "delivery_type": request.delivery_type,
        "borewell_size": (request.borewell_size, request.borewell_unit),
        "well_depth": (request.well_depth, request.well_depth_unit),
        "motor_power_hp": request.motor_power_hp,
        "num_floors": resolved_num_floors,
        "roof_tank_capacity": request.roof_tank_capacity if resolved_num_floors > 0 else None,
    }

    uc = USE_CASES["water_transfer"]
    facts = {
        "delivery_type": request.delivery_type,
        "borewell_size": request.borewell_size,
        "borewell_unit": request.borewell_unit,
        "min_borewell_size_inch": MIN_BOREWELL_SIZE,
        "max_borewell_size_inch": MAX_BOREWELL_SIZE,
        "well_depth": request.well_depth,
        "well_depth_unit": request.well_depth_unit,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    well_depth_ft = normalize_well_depth(request.well_depth, request.well_depth_unit)
    target_head_m = water_transfer_calculate_head(well_depth_ft, resolved_num_floors)

    target_head = target_head_m if request.well_depth_unit == "m" else m_to_ft(target_head_m)
    head_unit = request.well_depth_unit

    confirm_oversize = request.confirm_oversize
    explicitly_declined = False
    if request.confirm_oversize_text is not None:
        try:
            confirm_oversize = llm_parser.parse_yes_no(request.confirm_oversize_text)
            explicitly_declined = not confirm_oversize
        except llm_parser.AmbiguousConfirmationError:
            confirm_oversize = False

    try:
        recommendation = uc.select_pump(answers)
    except BorewellTooSmallError as e:
        return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)
    except BorewellOversizeConfirmationRequired as e:
        if explicitly_declined:
            return WaterTransferResponse(
                status="rejected", message=_explain(OVERSIZE_DECLINE_MESSAGE, facts), target_head=target_head
            )
        if not confirm_oversize:
            return WaterTransferResponse(status="confirmation_required", message=_explain(str(e), facts))
        answers["borewell_size"] = (MAX_BOREWELL_SIZE, "inch")
        try:
            recommendation = uc.select_pump(answers)
        except NoModelAvailableError as e:
            return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)
    except NoModelAvailableError as e:
        return WaterTransferResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    if request.well_depth_unit == "ft":
        recommendation.details["target_head"] = m_to_ft(recommendation.details["target_head"])
        recommendation.details["matched_head"] = m_to_ft(recommendation.details["matched_head"])
        recommendation.details["head_unit"] = "ft"
    else:
        recommendation.details["head_unit"] = "m"

    for alt in recommendation.tied_alternatives:
        if request.well_depth_unit == "ft":
            alt.details["target_head"] = m_to_ft(alt.details["target_head"])
            alt.details["matched_head"] = m_to_ft(alt.details["matched_head"])
            alt.details["head_unit"] = "ft"
        else:
            alt.details["head_unit"] = "m"

    return WaterTransferResponse(status="ok", recommendation=recommendation)


class TankFillingResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/tank_filling/recommend", response_model=TankFillingResponse)
def tank_filling_recommend(request: TankFillingRequest) -> TankFillingResponse:
    answers = {
        "inside_or_outside": request.inside_or_outside,
        "horizontal_or_vertical": request.horizontal_or_vertical,
        "tank_capacity": request.tank_capacity,
        "num_floors": request.num_floors,
        "motor_power_hp": request.motor_power_hp,
    }

    uc = USE_CASES["tank_filling"]
    facts = {
        "inside_or_outside": request.inside_or_outside,
        "horizontal_or_vertical": request.horizontal_or_vertical,
        "tank_capacity": request.tank_capacity,
        "num_floors": request.num_floors,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    target_head = tank_filling_calculate_head(request.num_floors)

    try:
        recommendation = uc.select_pump(answers)
    except NoTankFillingMatchError as e:
        return TankFillingResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    return TankFillingResponse(status="ok", recommendation=recommendation)


class PressureBoostingResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/pressure_boosting/recommend", response_model=PressureBoostingResponse)
def pressure_boosting_recommend(request: PressureBoostingRequest) -> PressureBoostingResponse:
    answers = {
        "num_floors": request.num_floors,
        "bathrooms_per_floor": request.bathrooms_per_floor,
    }

    uc = USE_CASES["pressure_boosting"]
    facts = {
        "num_floors": request.num_floors,
        "bathrooms_per_floor": request.bathrooms_per_floor,
    }
    target_head = pressure_boosting_calculate_head(request.num_floors)

    try:
        recommendation = uc.select_pump(answers)
    except NoPressureBoostingMatchError as e:
        return PressureBoostingResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    return PressureBoostingResponse(status="ok", recommendation=recommendation)


class DewateringResponse(BaseModel):
    status: str
    message: str | None = None
    recommendation: PumpRecommendation | None = None
    target_head: float | None = None


@app.post("/dewatering/recommend", response_model=DewateringResponse)
def dewatering_recommend(request: DewateringRequest) -> DewateringResponse:
    answers = {
        "depth_of_pit": (request.depth_of_pit, request.depth_of_pit_unit),
        "motor_power_hp": request.motor_power_hp,
    }

    uc = USE_CASES["dewatering"]
    facts = {
        "depth_of_pit": request.depth_of_pit,
        "depth_of_pit_unit": request.depth_of_pit_unit,
        "desired_motor_power_hp": request.motor_power_hp,
    }
    depth_of_pit_ft = normalize_depth_of_pit(request.depth_of_pit, request.depth_of_pit_unit)
    target_head_m = dewatering_calculate_head(depth_of_pit_ft)
    target_head = target_head_m if request.depth_of_pit_unit == "m" else m_to_ft(target_head_m)

    try:
        recommendation = uc.select_pump(answers)
    except NoDewateringMatchError as e:
        return DewateringResponse(status="rejected", message=_explain(str(e), facts), target_head=target_head)

    if request.depth_of_pit_unit == "ft":
        recommendation.details["target_head"] = m_to_ft(recommendation.details["target_head"])
        recommendation.details["matched_head"] = m_to_ft(recommendation.details["matched_head"])
        recommendation.details["head_unit"] = "ft"
    else:
        recommendation.details["head_unit"] = "m"

    for alt in recommendation.tied_alternatives:
        if request.depth_of_pit_unit == "ft":
            alt.details["target_head"] = m_to_ft(alt.details["target_head"])
            alt.details["matched_head"] = m_to_ft(alt.details["matched_head"])
            alt.details["head_unit"] = "ft"
        else:
            alt.details["head_unit"] = "m"

    return DewateringResponse(status="ok", recommendation=recommendation)


SEND_PUMP_DATA_URL = "https://wiloscan.pumpsearch.com/PumpManagement_V4/api/chatbot/send-selected-pump-mail"


@app.post("/send-pump-data")
def send_pump_data(request: SendPumpDataRequest) -> dict:
    """Proxy pump/user data to the external pump-search API, avoiding browser CORS."""
    api_key = os.environ.get("SEND_PUMP_DATA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="SEND_PUMP_DATA_API_KEY is not configured")

    try:
        response = httpx.post(
            SEND_PUMP_DATA_URL,
            json=request.model_dump(),
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            },
            timeout=30,
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach external API: {e}") from e

    try:
        body = response.json()
    except ValueError:
        body = response.text

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=body)

    return body


_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
