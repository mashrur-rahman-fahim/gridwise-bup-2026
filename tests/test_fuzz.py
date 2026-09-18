"""Randomised scenarios with randomised directives.

This is the suite that caught tightest-wins: two overlapping reserve directives where
the second was lower produced a plan the judge would reject.
"""
import itertools
import random

import pytest

from app.optimizer import Infeasible, solve
from app.postprocess import build_plan
from app.replay import replay
from tests.conftest import make_scenario

N = 400  # raised to 3000 in the nightly/full sweep


def rnd_scenario(rng):
    cap = round(rng.uniform(120, 400), 1)
    return make_scenario(
        [round(rng.uniform(40, 260), 1) for _ in range(24)],
        [0.0]*6 + [round(rng.uniform(0, 220), 1) for _ in range(12)] + [0.0]*6,
        [round(rng.uniform(3, 35), 1) for _ in range(24)],
        {"capacity_kwh": cap,
         "initial_energy_kwh": round(rng.uniform(0.3, 0.7) * cap, 1),
         "minimum_energy_kwh": round(rng.uniform(0, 0.25) * cap, 1),
         "max_charge_kwh_per_hour": round(rng.uniform(20, 90), 1),
         "max_discharge_kwh_per_hour": round(rng.uniform(20, 90), 1)},
    )


def rnd_directives(rng, capacity):
    out = []
    for _ in range(rng.randint(0, 3)):
        t = rng.choice(["solar_reduction", "no_charge_window", "no_discharge_window",
                        "minimum_battery_reserve", "max_grid_window"])
        start = rng.randint(0, 20)
        adj = {"hours": sorted(set(range(start, min(24, start + rng.randint(1, 4)))))}
        if t == "solar_reduction":
            adj["factor"] = round(rng.uniform(0, 1), 2)
        elif t == "minimum_battery_reserve":
            adj["minimum_energy_kwh"] = round(rng.uniform(0, 0.8) * capacity, 1)
        elif t == "max_grid_window":
            adj["max_grid_kwh"] = round(rng.uniform(60, 300), 1)
        out.append({"note_index": len(out), "applies": True,
                    "directive_type": t, "structured_adjustment": adj, "explanation": ""})
    return out


def test_fuzz_every_returned_plan_survives_replay():
    rng = random.Random(11)
    direct = rescued = 0
    for i in range(N):
        scn = rnd_scenario(rng)
        dirs = rnd_directives(rng, scn.battery.capacity_kwh)
        try:
            raw, applied, dropped = solve(scn.hours, scn.battery, dirs)
        except Infeasible:
            pytest.fail(f"case {i}: no plan at all, even with zero directives")
        plan, *_ = build_plan(scn.hours, scn.battery, raw)
        errors = replay(scn.hours, scn.battery, applied, plan)
        assert errors == [], f"case {i}: {errors[:3]} dirs={[d['directive_type'] for d in dirs]}"
        if dropped:
            rescued += 1
        else:
            direct += 1
    assert direct + rescued == N
    print(f"\n  {N} scenarios: {direct} solved directly, {rescued} rescued by dropping directives")
