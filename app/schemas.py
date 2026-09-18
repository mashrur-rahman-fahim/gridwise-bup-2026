"""Request and response models. These encode the specification's exact contract."""
import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _finite(v: float, name: str) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


# --------------------------------------------------------------------------- request


class HourIn(BaseModel):
    hour: int = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)

    @field_validator("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")
    @classmethod
    def _f(cls, v, info):
        return _finite(v, info.field_name)


class BatteryIn(BaseModel):
    capacity_kwh: float = Field(gt=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)

    @field_validator("*")
    @classmethod
    def _f(cls, v, info):
        return _finite(v, info.field_name)

    @model_validator(mode="after")
    def _coherent(self):
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh exceeds capacity_kwh")
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh exceeds capacity_kwh")
        return self


class ScenarioIn(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: List[str] = Field(min_length=1, max_length=3)
    hours: List[HourIn] = Field(min_length=24, max_length=24)
    battery: BatteryIn

    @field_validator("operator_notes")
    @classmethod
    def _notes_non_empty(cls, v):
        if any(not s or not s.strip() for s in v):
            raise ValueError("operator_notes entries must be non-empty")
        return v

    @field_validator("hours")
    @classmethod
    def _hours_exact(cls, v):
        if sorted(h.hour for h in v) != list(range(24)):
            raise ValueError("hours must contain each hour 0..23 exactly once")
        return v


# -------------------------------------------------------------------------- response


class DirectiveOut(BaseModel):
    note_index: int
    applies: bool
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    ]
    structured_adjustment: Optional[Dict[str, Any]]
    explanation: str


class PlanHourOut(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeOut(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveOut]
    hourly_plan: List[PlanHourOut]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
