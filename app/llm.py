"""Operator-note interpretation. This is the only component that reads English.

It receives the notes plus the two battery figures needed for percentage reserves,
and nothing else. The 24-hour demand/solar/tariff table is deliberately withheld:
what the model cannot see, it cannot invent.
"""
import logging
from typing import Any, Dict, List, Tuple

import httpx

from app.config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, LLM_TIMEOUT_S
from app.guardrail import GuardrailError, all_no_op, parse_model_output, validate
from app.repair import repair

log = logging.getLogger("gridwise.llm")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INSTRUCTIONS = """You convert campus operator notes into structured energy directives.

ALLOWED directive_type values (nothing else exists):
  solar_reduction          structured_adjustment = {"hours":[...], "factor": <0..1>}
  minimum_battery_reserve  structured_adjustment = {"hours":[...], "minimum_energy_kwh": <number>}
  no_charge_window         structured_adjustment = {"hours":[...]}
  no_discharge_window      structured_adjustment = {"hours":[...]}
  max_grid_window          structured_adjustment = {"hours":[...], "max_grid_kwh": <number>}
  no_op                    structured_adjustment = null

RULES - follow exactly:
1. HOURS are integers 0-23. Windows are START-INCLUSIVE and END-EXCLUSIVE.
   "1 PM to 3 PM" -> [13,14]        "noon until 2 PM" -> [12,13]
   "05:00 to 08:00" -> [5,6,7]      "at 11 PM" (single hour) -> [23]
   "10 PM until 2 AM" -> [0,1,22,23]   (wraps midnight; still ascending)
   "midnight to 4 AM" -> [0,1,2,3]
   Always output hours unique and in ASCENDING order.
2. FACTOR is the fraction of solar that REMAINS, never the fraction removed.
   "drops to 20%" -> 0.2        "80% reduction" -> 0.2      "one-fifth of normal" -> 0.2
   "only 60 percent usable" -> 0.6   "halves solar" -> 0.5   "a 40% drop" -> 0.6
3. RESERVES expressed as a percentage are a share of BATTERY CAPACITY. Do the
   arithmetic yourself and output kWh. Capacity is given below.
4. CHARGING means energy flowing INTO the battery. DISCHARGING means energy flowing
   OUT of the battery to serve demand. Operators phrase these loosely - decide by
   DIRECTION, not by the word "draw":
     into the battery  -> no_charge_window
       "pack intake", "battery intake", "charging the storage", "grid draw into the
       pack", "BESS grid draw", "mains import to the storage", "battery draw from
       the grid", "stop replenishing the pack"
     out of the battery -> no_discharge_window
       "pack output", "battery supplying the campus", "discharge", "drawing FROM
       the pack", "the pack must not export to the load"
   A note mentioning solar only as background context is still about the battery if
   the instruction targets the battery. Only use solar_reduction when the note says
   the usable SOLAR OUTPUT itself changes.
5. A note that does not change today's 24-hour electricity schedule is no_op.
   Staffing, menus, bookings, deadlines, meetings, paperwork, future months -> no_op.
   CAREFUL: the scenario IS the next 24 hours, so "tomorrow", "tonight", "today",
   "this evening" and "in the morning" all refer to the schedule you are building.
   Those are NORMAL and must still produce a real directive.
   Only mark a note no_op for timing when the change clearly falls OUTSIDE this
   24-hour horizon: "next week", "next month", "from Monday", "once the new feeder
   is installed", "going forward", "we are planning to", "starting next quarter".
   If in doubt and the note names specific hours, produce the directive.
6. applies = true for every directive except no_op. no_op has applies = false and
   structured_adjustment = null.
7. Output ONE entry per note, in note_index order 0,1,...N-1. Never invent a type.

Return ONLY a JSON array. No prose, no markdown."""


def build_prompt(notes: List[str], capacity_kwh: float, base_minimum_kwh: float) -> str:
    listing = "\n".join(f"[{i}] {n}" for i, n in enumerate(notes))
    return (
        f"{INSTRUCTIONS}\n\n"
        f"Battery capacity_kwh = {capacity_kwh}. Base minimum_energy_kwh = {base_minimum_kwh}.\n\n"
        f"OPERATOR NOTES ({len(notes)}):\n{listing}\n\n"
        f"JSON array of {len(notes)} entries:"
    )


async def _call_model(client: httpx.AsyncClient, model: str, prompt: str) -> str:
    response = await client.post(
        ENDPOINT.format(model=model),
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 2048,
            },
        },
        timeout=LLM_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        reason = payload.get("candidates", [{}])[0].get("finishReason", "unknown")
        raise GuardrailError(f"model returned no text (finishReason={reason})") from exc


async def interpret(notes: List[str], capacity_kwh: float,
                    base_minimum_kwh: float) -> Tuple[List[Dict[str, Any]], str]:
    """Interpret every note. Always returns a usable list - never raises.

    Degrades in stages: retry with the validation error fed back, then fall back to
    treating every note as no_op. A valid schedule missing one directive scores far
    better than an unavailable service.
    """
    count = len(notes)
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY is not configured; interpreting all notes as no_op")
        return all_no_op(count), "no-api-key"

    prompt = build_prompt(notes, capacity_kwh, base_minimum_kwh)
    attempts = [(GEMINI_MODEL, prompt)]

    async with httpx.AsyncClient() as client:
        last_error = ""
        for attempt, (model, text) in enumerate(attempts):
            try:
                raw = await _call_model(client, model, text)
                entries = validate(repair(parse_model_output(raw)), count, capacity_kwh)
                return entries, model
            except GuardrailError as exc:
                last_error = str(exc)
                log.warning("attempt %d rejected by guardrail: %s", attempt + 1, last_error)
                if len(attempts) == 1:
                    # one retry, telling the model exactly what was wrong
                    attempts.append((
                        GEMINI_MODEL,
                        f"{prompt}\n\nYour previous reply was rejected: {last_error}\n"
                        f"Return ONLY a valid JSON array of exactly {count} entries "
                        f"matching the schema above.",
                    ))
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("model transport error on %s: %s", model, last_error)
                if all(m != GEMINI_FALLBACK_MODEL for m, _ in attempts):
                    attempts.append((GEMINI_FALLBACK_MODEL, prompt))

        log.error("interpretation failed after %d attempts: %s", len(attempts), last_error)
        return all_no_op(count), "fallback-no_op"
