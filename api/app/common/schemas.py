from pydantic import BaseModel, Field


class Question(BaseModel):
    key: str
    prompt: str
    unit: str | None = None
    optional: bool = False
    allowed_units: list[str] | None = None
    requires_stated_unit: bool = False
    requires_integer: bool = False
    domain_context: str = ""


class WaterTransferRequest(BaseModel):
    borewell_size: float = Field(gt=0)
    borewell_unit: str
    well_depth: float = Field(gt=0)
    well_depth_unit: str
    motor_power_hp: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    roof_tank_capacity: float | None = Field(default=None, gt=0)
    confirm_oversize: bool = False
    confirm_oversize_text: str | None = None


class TankFillingRequest(BaseModel):
    inside_or_outside: str
    horizontal_or_vertical: str | None = None
    tank_capacity: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    motor_power_hp: float | None = Field(default=None, gt=0)


class PumpRecommendation(BaseModel):
    model_name: str
    art_no: int | None = None
    details: dict = {}
    tied_alternatives: list["PumpRecommendation"] = []


class ParsedAnswer(BaseModel):
    value: float | None = None
    unit: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    redirect_key: str | None = None
    gave_up: bool = False
    confirmation_message: str | None = None


class ParsedCategory(BaseModel):
    category: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    confirmation_message: str | None = None
