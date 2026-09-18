"""Build the published plan rows from raw solver values.

Two rules here are load-bearing:

1. NETTING. The solver is indifferent between charging and discharging in the same
   hour because the cost is identical, but the schema demands exactly one action per
   hour. Collapsing to the net is exactly cost-neutral: chg and dis appear in the
   model only as the difference (chg - dis), in both the balance equation and the
   battery recurrence. This holds only because the specification defines no
   round-trip efficiency loss - with a loss term the two would carry different
   weights and netting would silently change the battery level.

2. ROUND FIRST, THEN ACCUMULATE. The judge recomputes totals from the rows we
   publish. Accumulating unrounded values while publishing rounded ones leaves a
   drift that can approach the tolerance. Rounding first makes the rows
   self-consistent by construction.
"""
from typing import Dict, List, Tuple

from app.config import ROUND_DP, TOL


def build_plan(hours, battery, raw: Dict) -> Tuple[List[Dict], float, float, float]:
    H = {h.hour: h for h in hours}
    plan: List[Dict] = []
    energy = float(battery.initial_energy_kwh)

    for h in range(24):
        net = (raw["charge"][h] or 0.0) - (raw["discharge"][h] or 0.0)
        if net > TOL:
            action, magnitude = "charge", net
        elif net < -TOL:
            action, magnitude = "discharge", -net
        else:
            action, magnitude = "idle", 0.0

        magnitude = round(abs(magnitude), ROUND_DP)
        delta = magnitude if action == "charge" else (-magnitude if action == "discharge" else 0.0)
        energy = round(energy + delta, ROUND_DP)

        plan.append({
            "hour": h,
            "grid_kwh": round(max(0.0, raw["grid"][h] or 0.0), ROUND_DP),
            "solar_used_kwh": round(max(0.0, raw["solar"][h] or 0.0), ROUND_DP),
            "battery_action": action,
            "battery_kwh": magnitude,
            "battery_energy_after_kwh": energy,
        })

    # totals are computed from the PUBLISHED rows, never from the solver objective.
    # pulp.value(objective) returns None when every tariff is zero, which the
    # specification implies is a possible scenario.
    total_grid = round(sum(r["grid_kwh"] for r in plan), ROUND_DP)
    total_cost = round(sum(r["grid_kwh"] * H[r["hour"]].tariff_bdt_per_kwh for r in plan), ROUND_DP)
    peak_grid = round(max(r["grid_kwh"] for r in plan), ROUND_DP)
    return plan, total_grid, total_cost, peak_grid
