"""The contract auditor itself must be able to fail.

A check that cannot detect a defect proves nothing. These tests inject one defect at
a time into a known-good organizer reference answer and require the auditor to catch
each. The first case is the one that actually escaped: an entry shipped with a blank
`explanation` and every hand-written check passed it.
"""
import copy
import json
import pathlib

import pytest

from app.contract_audit import audit

CASES = json.loads(
    (pathlib.Path(__file__).parent.parent / "samples" / "public_sample_cases.json").read_text()
)["cases"]
CASE = CASES[0]


def test_auditor_accepts_the_organizers_own_reference_answer():
    assert audit(CASE["input"], CASE["expected_output"]) == []


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_auditor_accepts_every_public_reference_answer(case):
    assert audit(case["input"], case["expected_output"]) == []


DEFECTS = {
    "blank explanation": lambda r: r["directive_interpretation"][0].__setitem__("explanation", ""),
    "explanation removed": lambda r: r["directive_interpretation"][0].pop("explanation"),
    "scenario_id not echoed": lambda r: r.__setitem__("scenario_id", "WRONG"),
    "plan_summary blank": lambda r: r.__setitem__("plan_summary", "   "),
    "totals disagree with rows": lambda r: r.__setitem__("total_cost_bdt", r["total_cost_bdt"] + 50),
    "idle row carries energy": lambda r: r["hourly_plan"][0].update(
        {"battery_action": "idle", "battery_kwh": 7}),
    "hours not ascending": lambda r: r["directive_interpretation"][0]["structured_adjustment"]
        .__setitem__("hours", [13, 12]),
    "entries out of order": lambda r: r.__setitem__(
        "directive_interpretation", list(reversed(r["directive_interpretation"]))),
    "unexpected extra field": lambda r: r.__setitem__("debug_info", {"x": 1}),
    "solar overuse": lambda r: r["hourly_plan"][12].__setitem__("solar_used_kwh", 180.0),
    "battery ends off target": lambda r: r["hourly_plan"][23].__setitem__(
        "battery_energy_after_kwh", 99.0),
    "missing an hour": lambda r: r["hourly_plan"].pop(),
    "invented directive type": lambda r: r["directive_interpretation"][0].__setitem__(
        "directive_type", "reduce_demand"),
    "no_op marked as applying": lambda r: r["directive_interpretation"][1].__setitem__("applies", True),
    "negative grid value": lambda r: r["hourly_plan"][3].__setitem__("grid_kwh", -5.0),
}


@pytest.mark.parametrize("name,mutate", DEFECTS.items(), ids=list(DEFECTS))
def test_auditor_catches_injected_defect(name, mutate):
    broken = copy.deepcopy(CASE["expected_output"])
    mutate(broken)
    assert audit(CASE["input"], broken), f"auditor failed to notice: {name}"
