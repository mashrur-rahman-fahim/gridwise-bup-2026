"""Deterministic validation of model output.

Model output is untrusted structured data until every one of these checks passes.
A violation raises, which triggers one retry and then a no_op fallback; nothing here
ever repairs, guesses, or invents a directive.

The reserve-versus-capacity check in particular is operational, not cosmetic: a
hallucinated 500 kWh reserve on a 220 kWh battery makes the optimization infeasible,
which would cost the entire case. One check turns that into a retry.
"""
import json
import math
import re
from typing import Any, Dict, List

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

REQUIRED_KEYS: Dict[str, set] = {
    "solar_reduction": {"hours", "factor"},
    "minimum_battery_reserve": {"hours", "minimum_energy_kwh"},
    "no_charge_window": {"hours"},
    "no_discharge_window": {"hours"},
    "max_grid_window": {"hours", "max_grid_kwh"},
}


class GuardrailError(ValueError):
    """Model output violated the specification."""


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_model_output(raw: str) -> Any:
    """Recover a JSON array from whatever the model wrapped it in."""
    if not raw or not raw.strip():
        raise GuardrailError("empty model output")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError as exc:
            raise GuardrailError(f"model output is not valid JSON: {exc}") from exc
    raise GuardrailError("model output contains no JSON array")


def validate(entries: Any, note_count: int, capacity_kwh: float) -> List[Dict[str, Any]]:
    """Return normalised entries, or raise GuardrailError."""
    if not isinstance(entries, list):
        raise GuardrailError("expected a JSON array of interpretation entries")
    if len(entries) != note_count:
        raise GuardrailError(f"expected {note_count} entries, received {len(entries)}")

    seen = set()
    result: List[Dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise GuardrailError("interpretation entry is not an object")
        for key in ("note_index", "applies", "directive_type", "structured_adjustment"):
            if key not in entry:
                raise GuardrailError(f"entry missing required key '{key}'")

        index = entry["note_index"]
        if isinstance(index, bool) or not isinstance(index, int):
            raise GuardrailError("note_index must be an integer")
        if not 0 <= index < note_count:
            raise GuardrailError(f"note_index {index} does not identify an operator note")
        if index in seen:
            raise GuardrailError(f"note_index {index} appears more than once")
        seen.add(index)

        dtype = entry["directive_type"]
        if dtype not in ALLOWED_TYPES:
            raise GuardrailError(f"unsupported directive_type {dtype!r}")

        applies = entry["applies"]
        if not isinstance(applies, bool):
            raise GuardrailError("applies must be a boolean")

        adj = entry["structured_adjustment"]
        explanation = str(entry.get("explanation", ""))[:300]

        if dtype == "no_op":
            if applies is not False:
                raise GuardrailError("no_op must have applies=false")
            if adj is not None:
                raise GuardrailError("no_op must have a null structured_adjustment")
            result.append({"note_index": index, "applies": False, "directive_type": "no_op",
                           "structured_adjustment": None, "explanation": explanation})
            continue

        if applies is not True:
            raise GuardrailError(f"{dtype} must have applies=true; only no_op may be false")
        if not isinstance(adj, dict):
            raise GuardrailError(f"{dtype} requires a structured_adjustment object")
        if set(adj.keys()) != REQUIRED_KEYS[dtype]:
            raise GuardrailError(
                f"{dtype} expects keys {sorted(REQUIRED_KEYS[dtype])}, got {sorted(adj.keys())}")

        hours = adj["hours"]
        if not isinstance(hours, list) or not hours:
            raise GuardrailError("hours must be a non-empty list")
        for h in hours:
            if isinstance(h, bool) or not isinstance(h, int):
                raise GuardrailError(f"hour {h!r} is not an integer")
            if not 0 <= h <= 23:
                raise GuardrailError(f"hour {h} is outside 0..23")
        if len(set(hours)) != len(hours):
            raise GuardrailError("hours contains duplicates")
        hours = sorted(hours)

        clean: Dict[str, Any] = {"hours": hours}

        if dtype == "solar_reduction":
            factor = adj["factor"]
            if not _finite(factor):
                raise GuardrailError("factor must be a finite number")
            if not 0.0 <= factor <= 1.0:
                raise GuardrailError(f"factor {factor} is outside [0, 1]")
            clean["factor"] = float(factor)

        elif dtype == "minimum_battery_reserve":
            reserve = adj["minimum_energy_kwh"]
            if not _finite(reserve):
                raise GuardrailError("minimum_energy_kwh must be a finite number")
            if reserve < 0:
                raise GuardrailError("minimum_energy_kwh must be non-negative")
            if reserve > capacity_kwh:
                raise GuardrailError(
                    f"minimum_energy_kwh {reserve} exceeds battery capacity {capacity_kwh}")
            clean["minimum_energy_kwh"] = float(reserve)

        elif dtype == "max_grid_window":
            cap = adj["max_grid_kwh"]
            if not _finite(cap):
                raise GuardrailError("max_grid_kwh must be a finite number")
            if cap < 0:
                raise GuardrailError("max_grid_kwh must be non-negative")
            clean["max_grid_kwh"] = float(cap)

        result.append({"note_index": index, "applies": True, "directive_type": dtype,
                       "structured_adjustment": clean, "explanation": explanation})

    result.sort(key=lambda e: e["note_index"])
    return result


def all_no_op(note_count: int, reason: str = "") -> List[Dict[str, Any]]:
    """Safe fallback: every note marked as not affecting the schedule."""
    text = "Note could not be interpreted reliably; treated as not affecting the schedule."
    return [{"note_index": i, "applies": False, "directive_type": "no_op",
             "structured_adjustment": None, "explanation": text} for i in range(note_count)]
