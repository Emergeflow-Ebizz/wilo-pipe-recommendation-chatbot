from app.common.catalog_loader import load_sheet
from app.common.schemas import PumpRecommendation
from app.common.units import ft_to_m, m_to_ft, mm_to_inch
from app.use_cases.base import UseCase
from app.use_cases.water_transfer.questions import QUESTIONS
from app.use_cases.water_transfer.sheet_map import (
    MAX_BOREWELL_SIZE,
    MIN_BOREWELL_SIZE,
    SHEET_MAP,
)

FLOOR_HEIGHT_FT = 12
HEAD_SAFETY_FACTOR = 1.3

OVERSIZE_CONFIRM_MESSAGE = (
    f"We only have up to {MAX_BOREWELL_SIZE} inch available. "
    f"Would you like to proceed with the {MAX_BOREWELL_SIZE} inch model?"
)
UNDERSIZE_REJECT_MESSAGE = (
    f"No suitable pump is available for a borewell smaller than {MIN_BOREWELL_SIZE} inch."
)
OVERSIZE_DECLINE_MESSAGE = "No pump model available for this borewell size"
NO_MODEL_AVAILABLE_MESSAGE = "No pump model available with us for this requirement."


class BorewellTooSmallError(Exception):
    pass


class BorewellOversizeConfirmationRequired(Exception):
    """Raised when the borewell size exceeds the largest available sheet.

    Caller must ask the user OVERSIZE_CONFIRM_MESSAGE; if they confirm, retry
    sheet resolution with MAX_BOREWELL_SIZE. If they decline, raise
    BorewellOversizeDeclined instead of retrying.
    """


class BorewellOversizeDeclined(Exception):
    """Raised when the user declines to proceed with the max available size."""


class NoModelAvailableError(Exception):
    """Raised when no model in the resolved catalog(s) reaches the target head."""


def normalize_borewell_size(value: float, unit: str) -> float:
    """Normalize a borewell size answer to inches."""
    if unit == "mm":
        return mm_to_inch(value)
    if unit == "inch":
        return value
    raise ValueError(f"Unsupported borewell size unit: {unit}")


def normalize_well_depth(value: float, unit: str) -> float:
    """Normalize a well depth answer to feet."""
    if unit == "m":
        return m_to_ft(value)
    if unit == "ft":
        return value
    raise ValueError(f"Unsupported well depth unit: {unit}")


def resolve_sheet_filename(borewell_size: float) -> list[str]:
    if borewell_size < MIN_BOREWELL_SIZE:
        raise BorewellTooSmallError(UNDERSIZE_REJECT_MESSAGE)

    if borewell_size > MAX_BOREWELL_SIZE:
        raise BorewellOversizeConfirmationRequired(OVERSIZE_CONFIRM_MESSAGE)

    available_sizes = sorted(SHEET_MAP)
    matched_size = max(size for size in available_sizes if size <= borewell_size)
    return SHEET_MAP[matched_size]


def calculate_head(depth_of_bore_ft: float, num_floors: int) -> float:
    """Calculate head in feet, then convert to meters for catalog matching."""
    head_ft = (depth_of_bore_ft + (num_floors * FLOOR_HEIGHT_FT)) * HEAD_SAFETY_FACTOR
    return ft_to_m(head_ft)


def _match_head(catalog: dict, target_head: float) -> float:
    """Match target head to a head in the catalog.

    If target_head truncates to a whole number that exists, use it.
    Otherwise round UP to the next higher listed head.
    """
    heads = {
        point["head"]
        for model in catalog.values()
        for point in model["performance_curves"]
    }

    whole_target = int(target_head)
    if whole_target in heads:
        return whole_target

    candidates = sorted(h for h in heads if h > whole_target)
    if not candidates:
        raise NoModelAvailableError(NO_MODEL_AVAILABLE_MESSAGE)
    return candidates[0]


def _flow_at_head(model: dict, head: float) -> float | None:
    for point in model["performance_curves"]:
        if point["head"] == head:
            return point["flow"]
    return None


def select_model(catalog: dict, target_head: float, desired_hp: float | None) -> list[tuple[str, dict]]:
    """Return every model tied for best match at the matched head.

    Usually this is a single model, but the catalog can contain exact
    duplicates (same HP, same full performance curve, different art_no) -
    in that case all of them are returned rather than picking one arbitrarily.
    """
    matched_head = _match_head(catalog, target_head)

    candidates = [
        (name, model)
        for name, model in catalog.items()
        if _flow_at_head(model, matched_head) is not None
    ]

    if desired_hp is not None:
        exact_hp_matches = [
            (name, model) for name, model in candidates if model["motor_rating"]["hp"] == desired_hp
        ]
        if exact_hp_matches:
            candidates = exact_hp_matches
        else:
            lowest_hp = min(model["motor_rating"]["hp"] for _, model in candidates)
            candidates = [(name, model) for name, model in candidates if model["motor_rating"]["hp"] == lowest_hp]
    else:
        lowest_hp = min(model["motor_rating"]["hp"] for _, model in candidates)
        candidates = [(name, model) for name, model in candidates if model["motor_rating"]["hp"] == lowest_hp]

    best_flow = max(_flow_at_head(model, matched_head) for _, model in candidates)
    return [
        (name, model)
        for name, model in candidates
        if _flow_at_head(model, matched_head) == best_flow
    ]


def calculate_fill_time_minutes(tank_capacity_litres: float, flow_lpm: float) -> float:
    return tank_capacity_litres / flow_lpm


class WaterTransferUseCase(UseCase):
    slug = "water_transfer"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        """Returns the best-matched model.

        If the catalog has exact duplicates at the matched head (identical HP
        and performance curve, only art_no/name differ), the extras are
        listed in tied_alternatives instead of being silently discarded.
        """
        borewell_size = normalize_borewell_size(*answers["borewell_size"])
        well_depth_ft = normalize_well_depth(*answers["well_depth"])
        num_floors = answers["num_floors"]
        desired_hp = answers.get("motor_power_hp")
        tank_capacity_litres = answers.get("roof_tank_capacity") if num_floors != 0 else None

        sheet_filenames = resolve_sheet_filename(borewell_size)
        catalog = {}
        for filename in sheet_filenames:
            catalog.update(load_sheet(filename))

        target_head = calculate_head(well_depth_ft, num_floors)
        matched_models = select_model(catalog, target_head, desired_hp)

        matched_head = _match_head(catalog, target_head)

        def build_recommendation(model_name: str, model: dict) -> PumpRecommendation:
            flow_lpm = _flow_at_head(model, matched_head)
            details = {
                "sheet": ", ".join(sheet_filenames),
                "target_head": target_head,
                "matched_head": matched_head,
                "flow": flow_lpm,
                "hp": model["motor_rating"]["hp"],
                "phase": model.get("phase"),
            }
            if tank_capacity_litres is not None and flow_lpm:
                details["fill_time_minutes"] = calculate_fill_time_minutes(tank_capacity_litres, flow_lpm)
            return PumpRecommendation(model_name=model_name, art_no=model.get("art_no"), details=details)

        primary_name, primary_model = matched_models[0]
        recommendation = build_recommendation(primary_name, primary_model)
        recommendation.tied_alternatives = [
            build_recommendation(name, model) for name, model in matched_models[1:]
        ]
        return recommendation

    def select_pump_with_trace(self, answers: dict) -> tuple[PumpRecommendation, list[dict]]:
        """Same logic as select_pump, but also returns a step-by-step trace for display in the debug UI."""
        trace: list[dict] = []

        raw_borewell_size, borewell_unit = answers["borewell_size"]
        raw_well_depth, well_depth_unit = answers["well_depth"]

        borewell_size = normalize_borewell_size(raw_borewell_size, borewell_unit)
        trace.append({
            "step": "Normalize borewell size",
            "input": f"{raw_borewell_size} {borewell_unit}",
            "output": f"{borewell_size:.3f} inch",
        })

        well_depth_ft = normalize_well_depth(raw_well_depth, well_depth_unit)
        trace.append({
            "step": "Normalize well depth",
            "input": f"{raw_well_depth} {well_depth_unit}",
            "output": f"{well_depth_ft:.3f} ft",
        })

        num_floors = answers["num_floors"]
        desired_hp = answers.get("motor_power_hp")
        tank_capacity_litres = answers.get("roof_tank_capacity") if num_floors != 0 else None

        sheet_filenames = resolve_sheet_filename(borewell_size)
        trace.append({
            "step": "Resolve catalog sheet",
            "input": f"borewell size {borewell_size:.3f} inch, available sizes {sorted(SHEET_MAP)}",
            "output": ", ".join(sheet_filenames),
        })

        catalog = {}
        for filename in sheet_filenames:
            catalog.update(load_sheet(filename))
        trace.append({
            "step": "Load sheet",
            "input": ", ".join(sheet_filenames),
            "output": f"{len(catalog)} model(s) loaded",
        })

        target_head = calculate_head(well_depth_ft, num_floors)
        trace.append({
            "step": "Calculate head (ft, then convert to meters)",
            "input": f"(({well_depth_ft:.3f} ft + ({num_floors} floors * {FLOOR_HEIGHT_FT} ft)) * {HEAD_SAFETY_FACTOR}) converted to meters",
            "output": f"{target_head:.3f} m",
        })

        matched_head = _match_head(catalog, target_head)
        trace.append({
            "step": "Match head (try exact whole number, else round up)",
            "input": f"target head {target_head:.3f}",
            "output": f"matched head {matched_head}",
        })

        matched_models = select_model(catalog, target_head, desired_hp)
        model_name, model = matched_models[0]
        trace.append({
            "step": "Select model at matched head",
            "input": f"desired HP: {desired_hp if desired_hp is not None else 'not given (use lowest HP)'}",
            "output": (
                f"{model_name} (HP {model['motor_rating']['hp']})"
                + (f" - tied with {len(matched_models) - 1} identical model(s)" if len(matched_models) > 1 else "")
            ),
        })

        flow_lpm = _flow_at_head(model, matched_head)
        trace.append({
            "step": "Read flow at matched head",
            "input": f"model {model_name}, head {matched_head}",
            "output": f"{flow_lpm} LPM",
        })

        details = {
            "sheet": ", ".join(sheet_filenames),
            "target_head": target_head,
            "matched_head": matched_head,
            "flow": flow_lpm,
            "hp": model["motor_rating"]["hp"],
            "phase": model.get("phase"),
        }
        if tank_capacity_litres is not None and flow_lpm:
            fill_time = calculate_fill_time_minutes(tank_capacity_litres, flow_lpm)
            details["fill_time_minutes"] = fill_time
            trace.append({
                "step": "Calculate fill time",
                "input": f"{tank_capacity_litres} litres / {flow_lpm} LPM",
                "output": f"{fill_time:.2f} minutes",
            })

        recommendation = PumpRecommendation(
            model_name=model_name,
            art_no=model.get("art_no"),
            details=details,
            tied_alternatives=[
                PumpRecommendation(model_name=name, art_no=m.get("art_no"), details=details)
                for name, m in matched_models[1:]
            ],
        )
        return recommendation, trace
