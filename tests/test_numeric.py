"""Floating-point behaviour. The judge recomputes our totals from our own rows,
so the published rows must be internally consistent well inside 0.01."""
import pytest

from app.optimizer import solve
from app.postprocess import build_plan
from app.replay import recompute_totals, replay
from tests.conftest import batt, directive, flat, make_scenario

CASES = [
    ("awkward thirds", make_scenario(flat(33.3333333), flat(0), flat(7.7777777), batt()), []),
    ("factor one third", make_scenario(flat(150), [0]*6+[123.456789]*12+[0]*6, flat(11.11), batt()),
     [directive("solar_reduction", {"hours": list(range(6, 18)), "factor": 1/3})]),
    ("tiny scale", make_scenario(flat(0.001), flat(0), flat(0.001),
        batt(capacity_kwh=0.01, initial_energy_kwh=0.005, minimum_energy_kwh=0.001,
             max_charge_kwh_per_hour=0.002, max_discharge_kwh_per_hour=0.002)), []),
    ("huge scale", make_scenario(flat(1e6), flat(0), flat(30),
        batt(capacity_kwh=1e6, initial_energy_kwh=5e5, minimum_energy_kwh=1e5,
             max_charge_kwh_per_hour=2e5, max_discharge_kwh_per_hour=2e5)), []),
    ("extreme tariff spread", make_scenario(flat(150), flat(0), [0.001]*12+[999]*12, batt()), []),
    ("reserve just under capacity", make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("minimum_battery_reserve", {"hours": [18, 19], "minimum_energy_kwh": 219.995})]),
    ("grid cap fractionally below demand", make_scenario(flat(150), flat(0), flat(10), batt()),
     [directive("max_grid_window", {"hours": [5, 6], "max_grid_kwh": 149.999})]),
]


@pytest.mark.parametrize("name,scn,dirs", CASES, ids=[n for n, _, _ in CASES])
def test_rows_are_self_consistent(name, scn, dirs):
    raw, applied, dropped = solve(scn.hours, scn.battery, dirs)
    plan, tg, tc, pk = build_plan(scn.hours, scn.battery, raw)

    assert replay(scn.hours, scn.battery, applied, plan) == []

    # the battery trajectory must reproduce exactly from the PUBLISHED magnitudes
    energy = scn.battery.initial_energy_kwh
    for row in plan:
        k = row["battery_kwh"]
        energy += k if row["battery_action"] == "charge" else (
            -k if row["battery_action"] == "discharge" else 0)
        assert abs(energy - row["battery_energy_after_kwh"]) < 1e-9, \
            f"{name}: battery drift at hour {row['hour']}"

    assert abs(energy - scn.battery.initial_energy_kwh) < 0.01, f"{name}: end-of-day drift"

    rg, rc, rp = recompute_totals(scn.hours, plan)
    assert abs(rg - tg) < 0.01 and abs(rc - tc) < 0.01 and abs(rp - pk) < 0.01
