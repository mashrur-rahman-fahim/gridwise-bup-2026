"""Request-envelope edge cases. Anything malformed must be rejected, not crash."""
import copy

import pytest
from pydantic import ValidationError

from app.schemas import ScenarioIn

GOOD = {
    "scenario_id": "X",
    "operator_notes": ["do not charge the battery from 2 AM to 4 AM"],
    "hours": [
        {"hour": h, "demand_kwh": 100, "solar_kwh": 0, "tariff_bdt_per_kwh": 10}
        for h in range(24)
    ],
    "battery": {
        "capacity_kwh": 220, "initial_energy_kwh": 110, "minimum_energy_kwh": 40,
        "max_charge_kwh_per_hour": 50, "max_discharge_kwh_per_hour": 50,
    },
}


def mut(fn):
    body = copy.deepcopy(GOOD)
    fn(body)
    return body


ACCEPT = [
    ("baseline", GOOD),
    ("hours shuffled", mut(lambda b: b["hours"].reverse())),
    ("huge but finite demand", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", 1e308))),
    ("very long note", mut(lambda b: b.__setitem__("operator_notes", ["x" * 12000]))),
    ("long scenario_id", mut(lambda b: b.__setitem__("scenario_id", "z" * 500))),
    ("max_charge zero", mut(lambda b: b["battery"].__setitem__("max_charge_kwh_per_hour", 0))),
    ("unknown extra field", mut(lambda b: b.__setitem__("extra", {"a": 1}))),
    ("three notes", mut(lambda b: b.__setitem__("operator_notes", ["a", "b", "c"]))),
]

REJECT = [
    ("23 hours", mut(lambda b: b["hours"].pop())),
    ("25 hours", mut(lambda b: b["hours"].append(dict(b["hours"][0])))),
    ("duplicate hour", mut(lambda b: b["hours"].__setitem__(5, dict(b["hours"][5], hour=4)))),
    ("hour 24", mut(lambda b: b["hours"][3].__setitem__("hour", 24))),
    ("hour -1", mut(lambda b: b["hours"][3].__setitem__("hour", -1))),
    ("negative demand", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", -5))),
    ("negative tariff", mut(lambda b: b["hours"][2].__setitem__("tariff_bdt_per_kwh", -1))),
    ("demand as text", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", "abc"))),
    ("demand null", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", None))),
    ("demand inf", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", float("inf")))),
    ("demand nan", mut(lambda b: b["hours"][2].__setitem__("demand_kwh", float("nan")))),
    ("hour missing field", mut(lambda b: b["hours"][2].pop("solar_kwh"))),
    ("zero notes", mut(lambda b: b.__setitem__("operator_notes", []))),
    ("four notes", mut(lambda b: b.__setitem__("operator_notes", ["a", "b", "c", "d"]))),
    ("empty note", mut(lambda b: b.__setitem__("operator_notes", [""]))),
    ("whitespace note", mut(lambda b: b.__setitem__("operator_notes", ["   "]))),
    ("note not a string", mut(lambda b: b.__setitem__("operator_notes", [123]))),
    ("no scenario_id", mut(lambda b: b.pop("scenario_id"))),
    ("empty scenario_id", mut(lambda b: b.__setitem__("scenario_id", ""))),
    ("no battery", mut(lambda b: b.pop("battery"))),
    ("capacity zero", mut(lambda b: b["battery"].__setitem__("capacity_kwh", 0))),
    ("capacity negative", mut(lambda b: b["battery"].__setitem__("capacity_kwh", -10))),
    ("minimum above capacity", mut(lambda b: b["battery"].__setitem__("minimum_energy_kwh", 900))),
    ("initial above capacity", mut(lambda b: b["battery"].__setitem__("initial_energy_kwh", 900))),
    ("hours not a list", mut(lambda b: b.__setitem__("hours", "nope"))),
]


@pytest.mark.parametrize("name,body", ACCEPT, ids=[n for n, _ in ACCEPT])
def test_accepts_valid(name, body):
    ScenarioIn(**body)


@pytest.mark.parametrize("name,body", REJECT, ids=[n for n, _ in REJECT])
def test_rejects_invalid(name, body):
    with pytest.raises((ValidationError, ValueError, TypeError)):
        ScenarioIn(**body)
