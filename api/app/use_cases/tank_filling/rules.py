from app.common.catalog_loader import load_sheet
from app.common.schemas import PumpRecommendation
from app.common.units import ft_to_m
from app.use_cases.base import UseCase
from app.use_cases.tank_filling.questions import QUESTIONS
from app.use_cases.tank_filling.sheet_map import MONOBLOCK_SEQUENCE, OPENWELL_SHEETS

FLOOR_HEIGHT_FT = 12
HEAD_SAFETY_FACTOR = 1.3

NO_MODEL_AVAILABLE_MESSAGE = "We do not have the pump specification required by you."


class NoTankFillingMatchError(Exception):
    pass


def calculate_head(num_floors: int) -> float:
    """Calculate head in feet, then convert to meters for catalog matching."""
    head_ft = (num_floors * FLOOR_HEIGHT_FT) * HEAD_SAFETY_FACTOR
    return ft_to_m(head_ft)


def _heads_in_catalog(catalog: dict) -> set:
    return {
        point["head"]
        for model in catalog.values()
        for point in model["performance_curves"]
    }


def _has_exact_head(catalog: dict, whole_target: int) -> bool:
    return whole_target in _heads_in_catalog(catalog)


def _match_head(catalog: dict, target_head: float) -> float:
    """Match target head to a head in the catalog.

    Truncate target_head to a whole number first. If that whole number
    exists as a head value, use it exactly. Otherwise round UP to the next
    higher head value present. Never round down, never interpolate.
    """
    heads = _heads_in_catalog(catalog)

    whole_target = int(target_head)
    if whole_target in heads:
        return whole_target

    candidates = sorted(h for h in heads if h > whole_target)
    if not candidates:
        raise NoTankFillingMatchError(NO_MODEL_AVAILABLE_MESSAGE)
    return candidates[0]


def _flow_at_head(model: dict, head: float) -> float | None:
    for point in model["performance_curves"]:
        if point["head"] == head:
            return point["flow"]
    return None


def select_model(catalog: dict, target_head: float, desired_hp: float | None) -> list[tuple[str, dict]]:
    """Return every model tied for best match at the matched head.

    If desired_hp is given and present at the matched head, use it exactly.
    Otherwise (no desired_hp, or desired_hp not present) fall back to the
    lowest HP at the matched head, then the highest flow as tie-break. Exact
    duplicates (same HP, same flow, different art_no) are all returned.
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


def _load_filtered_sheet(sheet_file: str, name_prefix: str | None) -> dict:
    catalog = load_sheet(sheet_file)
    if name_prefix:
        catalog = {
            name: model
            for name, model in catalog.items()
            if name.startswith(name_prefix)
        }
    return catalog


def resolve_monoblock_catalog(target_head: float, desired_hp: float | None) -> tuple[dict, str]:
    """Resolve which monoblock catalog to select from.

    Pass 1: walk MONOBLOCK_SEQUENCE in order (Khushal -> MPM -> Crown AXA ->
    Royal -> Emperor -> WHS-VN -> WHS-MN -> WHS-SN) looking for an EXACT
    (truncated) head match in each sheet. The first sheet with an exact
    match wins - regardless of desired_hp. If desired_hp isn't present at
    that head in that sheet, select_model() falls back to lowest HP, then
    highest flow, WITHIN THAT SAME SHEET (never a different sheet).

    Pass 2: if no sheet in the whole sequence has that exact head, walk the
    sequence again from the start. The first sheet that has ANY head higher
    than the target wins - round up to the lowest such head within that
    sheet. Same per-sheet HP fallback rule applies from there.

    Returns (catalog, sheet_name_for_trace). Raises NoTankFillingMatchError
    if no sheet anywhere has the exact head or anything higher.
    """
    whole_target = int(target_head)

    for sheet_name, sheet_file, name_prefix in MONOBLOCK_SEQUENCE:
        catalog = _load_filtered_sheet(sheet_file, name_prefix)
        if _has_exact_head(catalog, whole_target):
            return catalog, sheet_name

    for sheet_name, sheet_file, name_prefix in MONOBLOCK_SEQUENCE:
        catalog = _load_filtered_sheet(sheet_file, name_prefix)
        heads = _heads_in_catalog(catalog)
        if any(h > whole_target for h in heads):
            return catalog, sheet_name

    raise NoTankFillingMatchError(NO_MODEL_AVAILABLE_MESSAGE)


def resolve_openwell_catalog(orientation: str) -> dict:
    sheet_file = OPENWELL_SHEETS.get(orientation)
    if not sheet_file:
        raise ValueError(f"Unknown orientation: {orientation}")
    return load_sheet(sheet_file)


class TankFillingUseCase(UseCase):
    slug = "tank_filling"
    questions = QUESTIONS

    def select_pump(self, answers: dict) -> PumpRecommendation:
        inside_or_outside = answers["inside_or_outside"]
        horizontal_or_vertical = answers.get("horizontal_or_vertical")
        num_floors = answers["num_floors"]
        desired_hp = answers.get("motor_power_hp")
        tank_capacity_litres = answers.get("tank_capacity") if num_floors != 0 else None

        target_head = calculate_head(num_floors)

        def build_recommendation(model_name: str, model: dict, matched_head: float, extra_details: dict) -> PumpRecommendation:
            flow_lpm = _flow_at_head(model, matched_head)
            details = {
                "target_head": target_head,
                "matched_head": matched_head,
                "flow": flow_lpm,
                "hp": model["motor_rating"]["hp"],
                "phase": model.get("phase"),
                **extra_details,
            }
            if tank_capacity_litres is not None and flow_lpm:
                details["fill_time_minutes"] = calculate_fill_time_minutes(tank_capacity_litres, flow_lpm)
            return PumpRecommendation(model_name=model_name, art_no=model.get("art_no"), details=details)

        def build_from_catalog(catalog: dict, extra_details: dict) -> PumpRecommendation:
            matched_models = select_model(catalog, target_head, desired_hp)
            matched_head = _match_head(catalog, target_head)
            primary_name, primary_model = matched_models[0]
            recommendation = build_recommendation(primary_name, primary_model, matched_head, extra_details)
            recommendation.tied_alternatives = [
                build_recommendation(name, model, matched_head, extra_details)
                for name, model in matched_models[1:]
            ]
            return recommendation

        if inside_or_outside == "inside":
            if horizontal_or_vertical in ("horizontal", "vertical"):
                catalog = resolve_openwell_catalog(horizontal_or_vertical)
                return build_from_catalog(catalog, {"orientation": horizontal_or_vertical})

            # No orientation answered: recommend both horizontal and vertical independently.
            results = []
            for candidate_orientation in ("horizontal", "vertical"):
                catalog = resolve_openwell_catalog(candidate_orientation)
                try:
                    results.append(build_from_catalog(catalog, {"orientation": candidate_orientation}))
                except NoTankFillingMatchError:
                    continue

            if not results:
                raise NoTankFillingMatchError(NO_MODEL_AVAILABLE_MESSAGE)

            primary = results[0]
            primary.tied_alternatives = results[1:] + primary.tied_alternatives
            return primary

        elif inside_or_outside == "outside":
            catalog, sheet_name = resolve_monoblock_catalog(target_head, desired_hp)
            return build_from_catalog(catalog, {"sheet": sheet_name})

        else:
            raise ValueError(f"Unknown value for inside_or_outside: {inside_or_outside}")
