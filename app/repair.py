"""Coerce unambiguous model sloppiness before the guardrail runs.

Governing rule: repair only where there is exactly ONE sane reading. Anything
genuinely ambiguous is left alone so the guardrail rejects it and the retry can
correct it.

Rejecting a recoverable note is self-harm - it loses the interpretation credit AND
leaves the constraint unapplied, which invalidates the whole case. Guessing at an
ambiguous value is worse. This module sits exactly on that line.
"""
import math
from typing import Any, List

from app.guardrail import ALLOWED_TYPES, REQUIRED_KEYS


def _number(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        text = v.strip()
        percent = text.endswith("%")
        try:
            value = float(text.rstrip("%"))
        except ValueError:
            return v
        # "25%" means 0.25. A bare 25 is ambiguous (typo? percent?) so it is left
        # alone and rejected by the range check.
        return value / 100.0 if percent else value
    return v


def _as_int(v: Any) -> Any:
    v = _number(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and math.isfinite(v) and abs(v - round(v)) < 1e-9:
        return int(round(v))
    return v


def _as_bool(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return v


def repair(entries: Any) -> Any:
    if not isinstance(entries, list):
        return entries

    out: List[Any] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        e = dict(entry)

        # a missing index is unambiguous when the array lines up with the notes
        if e.get("note_index") is None:
            e["note_index"] = position
        e["note_index"] = _as_int(e["note_index"])
        e["applies"] = _as_bool(e.get("applies"))

        dtype = e.get("directive_type")
        if isinstance(dtype, str):
            dtype = e["directive_type"] = dtype.strip().lower()

        if dtype == "no_op":
            # the specification fixes this pairing, so there is nothing to guess
            e["applies"] = False
            e["structured_adjustment"] = None
            out.append(e)
            continue

        adj = e.get("structured_adjustment")
        if dtype in REQUIRED_KEYS and isinstance(adj, dict):
            adj = dict(adj)
            hours = adj.get("hours")
            if isinstance(hours, list):
                coerced = [_as_int(h) for h in hours]
                if all(isinstance(h, int) and not isinstance(h, bool) for h in coerced):
                    adj["hours"] = sorted(set(coerced))
            for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
                if key in adj:
                    adj[key] = _number(adj[key])
            adj = {k: v for k, v in adj.items() if k in REQUIRED_KEYS[dtype]}
            e["structured_adjustment"] = adj
            # a complete extraction is present, and only no_op may be false
            if set(adj.keys()) == REQUIRED_KEYS[dtype]:
                e["applies"] = True

        out.append(e)
    return out
