from app.common.catalog_loader import load_sheet
from app.common.schemas import PumpRecommendation
from app.common.units import ft_to_m
from app.use_cases.base import UseCase
from app.use_cases.pressure_boosting.questions import QUESTIONS
from app.use_cases.pressure_boosting.sheet_map import SHEET_SEQUENCE

FLOOR_HEIGHT_FT = 12
HEAD_SAFETY_FACTOR = 1.3
FLOW_PER_BATHROOM_LPM = 20
UTILISATION_FACTOR = 0.6

NO_MODEL_AVAILABLE_MESSAGE = "We do not have the pump specification required by you."


class NoPressureBoostingMatchError(Exception):
    pass


def calculate_head(num_floors: int) -> float:
    """Calculate head in feet (building height), then convert to meters for catalog matching."""
    head_ft = (num_floors * FLOOR_HEIGHT_FT) * HEAD_SAFETY_FACTOR
    return ft_to_m(head_ft)


def calculate_required_flow(num_floors: int, bathrooms_per_floor: int) -> float:
    total_bathrooms = num_floors * bathrooms_per_floor
    total_flow_lpm = total_bathrooms * FLOW_PER_BATHROOM_LPM
    return total_flow_lpm * UTILISATION_FACTOR


def _heads_in_catalog(catalog: dict) -> set:
    return {
        point["head"]
        for model in catalog.values()
        for point in model["performance_curves"]
    }


def _match_head(catalog: dict, target_head: float, decimal_mode: bool) -> float | None:
    """Match target head to a head in the catalog, or None if none is high enough.

    decimal_mode=True (PB only): round target_head to 1 decimal place; exact
    match if present, else next-higher head value present.
    decimal_mode=False (all other sheets): truncate target_head to a whole
    number; exact match if present, else next-higher whole-number head
    present. Never round down, never interpolate.
    """
    heads = _heads_in_catalog(catalog)

    if decimal_mode:
        target = round(target_head, 1)
    else:
        target = int(target_head)

    if target in heads:
        return target

    candidates = sorted(h for h in heads if h > target)
    if not candidates:
        return None
    return candidates[0]


def _flow_at_head(model: dict, head: float) -> float | None:
    for point in model["performance_curves"]:
        if point["head"] == head:
            return point["flow"]
    return None


def resolve_pressure_boosting_catalog(target_head: float) -> tuple[dict, str, float]:
    """Walk SHEET_SEQUENCE in order; the first sheet with any head >= target wins.

    Returns (catalog, sheet_name, matched_head). Raises
    NoPressureBoostingMatchError if no sheet in the sequence has a head high
    enough.
    """
    for sheet_name, sheet_file, decimal_mode in SHEET_SEQUENCE:
        catalog = load_sheet(sheet_file)
        matched_head = _match_head(catalog, target_head, decimal_mode)
        if matched_head is not None:
            return catalog, sheet_name, matched_head

    raise NoPressureBoostingMatchError(NO_MODEL_AVAILABLE_MESSAGE)


def select_model(catalog: dict, matched_head: float, required_flow_lpm: float | None) -> list[tuple[str, dict]]:
    """Return every model tied for best match at the matched head.

    No HP filtering (pressure_boosting has no motor-power question). If
    required_flow_lpm is given and a model's flow at the matched head equals
    it exactly, that wins. Otherwise pick the smallest flow that still meets
    or exceeds required_flow_lpm ("next higher flow"). If nothing at this
    head reaches required_flow_lpm (or no requirement was given), fall back
    to the highest flow actually available at that head. All within this one
    sheet/catalog - never looks at other sheets.
    """
    candidates = [
        (name, model)
        for name, model in catalog.items()
        if _flow_at_head(model, matched_head) is not None
    ]

    if required_flow_lpm is not None:
        exact_matches = [
            (name, model) for name, model in candidates if _flow_at_head(model, matched_head) == required_flow_lpm
        ]
        if exact_matches:
            candidates = exact_matches
        else:
            above = [
                (name, model)
                for name, model in candidates
                if _flow_at_head(model, matched_head) > required_flow_lpm
            ]
            if above:
                next_higher_flow = min(_flow_at_head(model, matched_head) for _, model in above)
                candidates = [(name, model) for name, model in above if _flow_at_head(model, matched_head) == next_higher_flow]
            else:
                highest_flow = max(_flow_at_head(model, matched_head) for _, model in candidates)
                candidates = [(name, model) for name, model in candidates if _flow_at_head(model, matched_head) == highest_flow]
    else:
        highest_flow = max(_flow_at_head(model, matched_head) for _, model in candidates)
        candidates = [(name, model) for name, model in candidates if _flow_at_head(model, matched_head) == highest_flow]

    return candidates


class PressureBoostingUseCase(UseCase):
    slug = "pressure_boosting"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        num_floors = answers["num_floors"]
        bathrooms_per_floor = answers["bathrooms_per_floor"]

        target_head = calculate_head(num_floors)
        required_flow_lpm = calculate_required_flow(num_floors, bathrooms_per_floor)

        catalog, sheet_name, matched_head = resolve_pressure_boosting_catalog(target_head)
        matched_models = select_model(catalog, matched_head, required_flow_lpm)

        def build_recommendation(model_name: str, model: dict) -> PumpRecommendation:
            flow_lpm = _flow_at_head(model, matched_head)
            details = {
                "sheet": sheet_name,
                "target_head": target_head,
                "matched_head": matched_head,
                "required_flow": required_flow_lpm,
                "flow": flow_lpm,
                "hp": model["motor_rating"]["hp"],
                "phase": model.get("phase"),
            }
            return PumpRecommendation(model_name=model_name, art_no=model.get("art_no"), details=details)

        primary_name, primary_model = matched_models[0]
        recommendation = build_recommendation(primary_name, primary_model)
        recommendation.tied_alternatives = [
            build_recommendation(name, model) for name, model in matched_models[1:]
        ]
        return recommendation
