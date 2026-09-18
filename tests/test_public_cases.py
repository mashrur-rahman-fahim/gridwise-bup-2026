"""The 10 public sample cases must be exactly optimal and pass an independent replay."""
import json
import pathlib

import pytest

from app.optimizer import solve
from app.postprocess import build_plan
from app.replay import recompute_totals, replay
from app.schemas import ScenarioIn

CASES = json.loads(
    (pathlib.Path(__file__).parent.parent / "samples" / "public_sample_cases.json").read_text()
)["cases"]


def _ids():
    return [c["id"] for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_public_case_is_valid_and_optimal(case):
    scenario = ScenarioIn(**case["input"])
    truth = case["expected_output"]["directive_interpretation"]

    raw, applied, dropped = solve(scenario.hours, scenario.battery, truth)
    assert dropped == [], f"unexpectedly infeasible, dropped {dropped}"

    plan, total_grid, total_cost, peak = build_plan(scenario.hours, scenario.battery, raw)

    errors = replay(scenario.hours, scenario.battery, truth, plan)
    assert errors == [], f"replay violations: {errors[:4]}"

    reference = case["expected_output"]["total_cost_bdt"]
    assert abs(total_cost - reference) <= 0.01, f"cost {total_cost} vs organizer optimal {reference}"

    rg, rc, rp = recompute_totals(scenario.hours, plan)
    assert abs(rg - total_grid) <= 0.01
    assert abs(rc - total_cost) <= 0.01
    assert abs(rp - peak) <= 0.01
