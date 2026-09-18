import pytest
from app.schemas import ScenarioIn

def make_scenario(demand, solar, tariff, battery, notes=None):
    return ScenarioIn(
        scenario_id="T",
        operator_notes=notes or ["placeholder note"],
        hours=[
            {"hour": h, "demand_kwh": demand[h], "solar_kwh": solar[h],
             "tariff_bdt_per_kwh": tariff[h]}
            for h in range(24)
        ],
        battery=battery,
    )

def flat(v):
    return [v] * 24

def batt(**kw):
    base = {"capacity_kwh": 220, "initial_energy_kwh": 110, "minimum_energy_kwh": 40,
            "max_charge_kwh_per_hour": 50, "max_discharge_kwh_per_hour": 50}
    base.update(kw)
    return base

def directive(t, adj, idx=0):
    return {"note_index": idx, "applies": t != "no_op", "directive_type": t,
            "structured_adjustment": adj, "explanation": ""}

@pytest.fixture
def mk():
    return make_scenario
