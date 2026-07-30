from pydantic import BaseModel, Field, field_validator


class Question(BaseModel):
    key: str
    prompt: str
    unit: str | None = None
    optional: bool = False
    allowed_units: list[str] | None = None
    requires_stated_unit: bool = False
    requires_integer: bool = False
    min_value: float | None = None
    domain_context: str = ""


class WaterTransferRequest(BaseModel):
    delivery_type: str
    borewell_size: float = Field(gt=0)
    borewell_unit: str
    well_depth: float = Field(gt=0)
    well_depth_unit: str
    motor_power_hp: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    roof_tank_capacity: float | None = Field(default=None, gt=0)
    confirm_oversize: bool = False
    confirm_oversize_text: str | None = None

    @field_validator("num_floors")
    @classmethod
    def validate_num_floors(cls, v, info):
        if info.data.get("delivery_type") == "elevated_tank" and v < 1:
            raise ValueError("num_floors must be at least 1 for elevated_tank delivery")
        return v


class TankFillingRequest(BaseModel):
    inside_or_outside: str
    horizontal_or_vertical: str | None = None
    tank_capacity: float | None = Field(default=None, gt=0)
    num_floors: int = Field(ge=0)
    motor_power_hp: float | None = Field(default=None, gt=0)


class PressureBoostingRequest(BaseModel):
    num_floors: int = Field(ge=1)
    bathrooms_per_floor: int = Field(ge=1)


class DewateringRequest(BaseModel):
    depth_of_pit: float = Field(gt=0)
    depth_of_pit_unit: str
    motor_power_hp: float | None = Field(default=None, gt=0)


class PumpRecommendation(BaseModel):
    model_name: str
    art_no: int | None = None
    details: dict = {}
    tied_alternatives: list["PumpRecommendation"] = []


class AdditionalAnswer(BaseModel):
    """A value the user volunteered for a DIFFERENT question than the one
    they were just asked, extracted from the same reply as the primary
    answer (e.g. "value unit borewell, value unit deep, number floors" answers
    borewell_size AND well_depth AND num_floors in one message).

    Unlike redirect_key (which fires when the reply does NOT answer the
    current question at all), additional_answers coexist with a normal
    primary value/unit - the current question's own answer is unaffected.
    """

    key: str
    value: float
    unit: str | None = None


class ParsedAnswer(BaseModel):
    value: float | None = None
    unit: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    redirect_key: str | None = None
    gave_up: bool = False
    confirmation_message: str | None = None
    additional_answers: list[AdditionalAnswer] = []


class ParsedCategory(BaseModel):
    category: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    skipped: bool = False
    confirmation_message: str | None = None


class PumpDataUserDetails(BaseModel):
    pincode: str
    name: str
    contactNumber: str
    email: str


class PumpDataSearchDetails(BaseModel):
    application: str
    RequiredHead: str
    RequiredPower: str


class PumpDataSelectedPump(BaseModel):
    pumpModel: str
    articleNo: str
    motorRating: str
    selectedHead: str
    selectedFlow: str
    features: str


class PumpDataPayload(BaseModel):
    userDetails: PumpDataUserDetails
    searchDetails: PumpDataSearchDetails
    selectedPump: PumpDataSelectedPump


class SendPumpDataRequest(BaseModel):
    data: PumpDataPayload
