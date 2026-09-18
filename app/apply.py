"""Turn validated directives into optimizer bounds.

Overlapping directives of the same type resolve to the MOST RESTRICTIVE value.
The specification states this for reserves - max(base, directive) - and the same
rule is applied consistently to grid caps and effective solar. Over-constraining
keeps a plan valid; under-constraining does not.
"""
from typing import Any, Dict, List, Set, Tuple


def build_bounds(hours, battery, directives: List[Dict[str, Any]]) -> Tuple[
    Dict[int, float], Set[int], Set[int], Dict[int, float], Dict[int, float]
]:
    eff = {h.hour: float(h.solar_kwh) for h in hours}
    no_charge: Set[int] = set()
    no_discharge: Set[int] = set()
    reserve: Dict[int, float] = {}
    grid_cap: Dict[int, float] = {}
    base_solar = {h.hour: float(h.solar_kwh) for h in hours}

    for d in directives:
        t = d["directive_type"]
        a = d.get("structured_adjustment")
        if t == "no_op" or not a:
            continue
        hrs = a["hours"]
        if t == "solar_reduction":
            for h in hrs:
                eff[h] = min(eff[h], base_solar[h] * a["factor"])
        elif t == "no_charge_window":
            no_charge |= set(hrs)
        elif t == "no_discharge_window":
            no_discharge |= set(hrs)
        elif t == "minimum_battery_reserve":
            for h in hrs:
                reserve[h] = max(reserve.get(h, 0.0), a["minimum_energy_kwh"])
        elif t == "max_grid_window":
            for h in hrs:
                grid_cap[h] = min(grid_cap.get(h, float("inf")), a["max_grid_kwh"])

    return eff, no_charge, no_discharge, reserve, grid_cap
