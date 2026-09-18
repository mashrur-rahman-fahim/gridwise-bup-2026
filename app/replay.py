"""Independent replay of a finished plan, mirroring the judge's own checks.

Deliberately written without importing the optimizer or reusing its helpers: if both
shared code, a shared misreading of the specification would be invisible. This walks
the schedule hour by hour from the raw request and the directives, exactly as the
judge does, and recomputes the three reported totals.
"""
from typing import Any, Dict, List

from app.config import TOL


def replay(hours, battery, directives: List[Dict[str, Any]], plan: List[Dict]) -> List[str]:
    """Return a list of violations. Empty list means the plan is valid."""
    errors: List[str] = []
    H = {h.hour: h for h in hours}
    b = battery

    # rebuild directive effects from scratch
    eff = {h: float(H[h].solar_kwh) for h in range(24)}
    no_charge, no_discharge = set(), set()
    reserve, grid_cap = {}, {}
    for d in directives:
        t = d["directive_type"]
        a = d.get("structured_adjustment")
        if t == "no_op" or not a:
            continue
        for h in a["hours"]:
            if t == "solar_reduction":
                eff[h] = min(eff[h], float(H[h].solar_kwh) * a["factor"])
            elif t == "no_charge_window":
                no_charge.add(h)
            elif t == "no_discharge_window":
                no_discharge.add(h)
            elif t == "minimum_battery_reserve":
                reserve[h] = max(reserve.get(h, 0.0), a["minimum_energy_kwh"])
            elif t == "max_grid_window":
                grid_cap[h] = min(grid_cap.get(h, float("inf")), a["max_grid_kwh"])

    seen = [r["hour"] for r in plan]
    if sorted(seen) != list(range(24)):
        errors.append("hourly_plan must contain each hour 0..23 exactly once")
        return errors

    energy = float(b.initial_energy_kwh)
    total_grid = total_cost = 0.0
    peak = 0.0

    for row in sorted(plan, key=lambda r: r["hour"]):
        h = row["hour"]
        grid, solar = row["grid_kwh"], row["solar_used_kwh"]
        action, kwh = row["battery_action"], row["battery_kwh"]

        if grid < -TOL or solar < -TOL or kwh < -TOL:
            errors.append(f"h{h}: negative value")
        if action == "idle" and abs(kwh) > TOL:
            errors.append(f"h{h}: idle must have battery_kwh 0")

        charge = kwh if action == "charge" else 0.0
        discharge = kwh if action == "discharge" else 0.0

        if solar > eff[h] + TOL:
            errors.append(f"h{h}: solar_used {solar} exceeds effective solar {eff[h]:.4f}")
        if abs(grid + solar + discharge - (H[h].demand_kwh + charge)) > TOL:
            errors.append(f"h{h}: energy balance violated")

        energy += charge - discharge
        if abs(energy - row["battery_energy_after_kwh"]) > TOL:
            errors.append(f"h{h}: battery_energy_after_kwh inconsistent")

        floor = max(b.minimum_energy_kwh, reserve.get(h, 0.0))
        if energy < floor - TOL or energy > b.capacity_kwh + TOL:
            errors.append(f"h{h}: battery energy {energy:.4f} outside [{floor}, {b.capacity_kwh}]")
        if charge > b.max_charge_kwh_per_hour + TOL:
            errors.append(f"h{h}: charge exceeds hourly limit")
        if discharge > b.max_discharge_kwh_per_hour + TOL:
            errors.append(f"h{h}: discharge exceeds hourly limit")
        if h in no_charge and charge > TOL:
            errors.append(f"h{h}: charged inside no_charge_window")
        if h in no_discharge and discharge > TOL:
            errors.append(f"h{h}: discharged inside no_discharge_window")
        if h in grid_cap and grid > grid_cap[h] + TOL:
            errors.append(f"h{h}: grid {grid} exceeds cap {grid_cap[h]}")

        total_grid += grid
        total_cost += grid * H[h].tariff_bdt_per_kwh
        peak = max(peak, grid)

    if abs(energy - b.initial_energy_kwh) > TOL:
        errors.append(f"end-of-day battery {energy:.4f} != initial {b.initial_energy_kwh}")

    return errors


def recompute_totals(hours, plan: List[Dict]):
    H = {h.hour: h for h in hours}
    total_grid = sum(r["grid_kwh"] for r in plan)
    total_cost = sum(r["grid_kwh"] * H[r["hour"]].tariff_bdt_per_kwh for r in plan)
    peak = max(r["grid_kwh"] for r in plan)
    return total_grid, total_cost, peak
