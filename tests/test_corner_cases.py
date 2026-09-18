"""Solver behaviour at the edges of the physical model."""
import pytest

from app.optimizer import Infeasible, solve
from app.postprocess import build_plan
from app.replay import replay
from tests.conftest import batt, directive, flat, make_scenario


def run(scn, directives):
    raw, applied, dropped = solve(scn.hours, scn.battery, directives)
    plan, tg, tc, pk = build_plan(scn.hours, scn.battery, raw)
    errors = replay(scn.hours, scn.battery, applied, plan)
    return plan, tc, errors, dropped


VALID = [
    ("solar floods, must curtail",
     make_scenario(flat(50), [0]*6+[400]*12+[0]*6, flat(10), batt()), []),
    ("factor 0 total blackout",
     make_scenario(flat(150), [0]*6+[200]*12+[0]*6, flat(10), batt()),
     [directive("solar_reduction", {"hours": list(range(6, 18)), "factor": 0.0})]),
    ("factor 1 no change",
     make_scenario(flat(150), [0]*6+[200]*12+[0]*6, flat(10), batt()),
     [directive("solar_reduction", {"hours": list(range(6, 18)), "factor": 1.0})]),
    ("zero tariff everywhere",
     make_scenario(flat(150), flat(0), flat(0), batt()), []),
    ("zero demand everywhere",
     make_scenario(flat(0), flat(0), flat(10), batt()), []),
    ("frozen battery",
     make_scenario(flat(150), flat(0), flat(10),
                   batt(capacity_kwh=110, minimum_energy_kwh=110)), []),
    ("midnight wrap no_charge",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("no_charge_window", {"hours": [0, 1, 22, 23]})]),
    ("no_charge all 24h",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("no_charge_window", {"hours": list(range(24))})]),
    ("no_discharge all 24h",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("no_discharge_window", {"hours": list(range(24))})]),
    ("both windows all 24h",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("no_charge_window", {"hours": list(range(24))}),
      directive("no_discharge_window", {"hours": list(range(24))}, 1)]),
    ("two reserves overlap, lower listed last",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("minimum_battery_reserve", {"hours": [10, 11, 12], "minimum_energy_kwh": 180}),
      directive("minimum_battery_reserve", {"hours": [10, 11, 12], "minimum_energy_kwh": 60}, 1)]),
    ("two solar reductions, weaker last",
     make_scenario(flat(150), [0]*6+[200]*12+[0]*6, flat(10), batt()),
     [directive("solar_reduction", {"hours": [10, 11], "factor": 0.1}),
      directive("solar_reduction", {"hours": [10, 11], "factor": 0.9}, 1)]),
    ("two grid caps overlap, looser last",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("max_grid_window", {"hours": [5, 6], "max_grid_kwh": 120}),
      directive("max_grid_window", {"hours": [5, 6], "max_grid_kwh": 300}, 1)]),
    ("no tariff spread, no arbitrage exists",
     make_scenario(flat(150), flat(0), flat(9), batt()), []),
    ("tiny battery vs huge demand",
     make_scenario(flat(500), flat(0), flat(12),
                   batt(capacity_kwh=60, initial_energy_kwh=30, minimum_energy_kwh=10,
                        max_charge_kwh_per_hour=5, max_discharge_kwh_per_hour=5)), []),
    ("grid cap exactly equals demand",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("max_grid_window", {"hours": [5, 6], "max_grid_kwh": 150})]),
]


@pytest.mark.parametrize("name,scn,dirs", VALID, ids=[n for n, _, _ in VALID])
def test_valid_corner_cases(name, scn, dirs):
    plan, cost, errors, dropped = run(scn, dirs)
    assert errors == [], f"{name}: {errors[:3]}"
    assert dropped == [], f"{name}: unexpectedly dropped {dropped}"
    assert len(plan) == 24
    for row in plan:
        assert row["battery_action"] in ("charge", "discharge", "idle")
        if row["battery_action"] == "idle":
            assert row["battery_kwh"] == 0


def test_two_overlapping_reserves_respect_the_tighter_floor():
    """Regression: last-directive-wins let the plan sink below the higher reserve."""
    scn = make_scenario(flat(150), flat(0), flat(10), batt())
    dirs = [directive("minimum_battery_reserve", {"hours": [10, 11, 12], "minimum_energy_kwh": 180}),
            directive("minimum_battery_reserve", {"hours": [10, 11, 12], "minimum_energy_kwh": 60}, 1)]
    plan, _, errors, _ = run(scn, dirs)
    assert errors == []
    for row in plan:
        if row["hour"] in (10, 11, 12):
            assert row["battery_energy_after_kwh"] >= 180 - 0.01


def test_zero_tariff_does_not_crash_and_costs_zero():
    """Regression: reading cost from the solver objective raised TypeError here."""
    scn = make_scenario(flat(150), flat(0), flat(0), batt())
    plan, cost, errors, _ = run(scn, [])
    assert errors == []
    assert cost == 0.0


def test_no_hour_both_charges_and_discharges():
    """Regression: the solver is indifferent; the schema is not."""
    scn = make_scenario(flat(150), [0]*6+[120]*12+[0]*6, flat(10),
                        batt(max_charge_kwh_per_hour=55, max_discharge_kwh_per_hour=55))
    plan, _, errors, _ = run(scn, [directive("no_charge_window", {"hours": [2, 3, 4]})])
    assert errors == []
    for row in plan:
        assert row["battery_action"] in ("charge", "discharge", "idle")


INFEASIBLE = [
    ("grid capped at zero with demand",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("max_grid_window", {"hours": [3], "max_grid_kwh": 0})]),
    ("reserve at h23 conflicts with neutrality",
     make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("minimum_battery_reserve", {"hours": [23], "minimum_energy_kwh": 200})]),
]


@pytest.mark.parametrize("name,scn,dirs", INFEASIBLE, ids=[n for n, _, _ in INFEASIBLE])
def test_infeasible_directives_are_dropped_not_crashed(name, scn, dirs):
    """Organizer scenarios are guaranteed feasible, so this means a bad extraction.
    The service must still return a valid plan rather than fail."""
    plan, cost, errors, dropped = run(scn, dirs)
    assert dropped != [], f"{name}: expected a directive to be dropped"
    assert errors == [], f"{name}: fallback plan still invalid: {errors[:3]}"
    assert len(plan) == 24
