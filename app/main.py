"""GridWise HTTP service. Two endpoints, exact names required by the specification."""
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.llm import interpret
from app.optimizer import Infeasible, solve
from app.postprocess import build_plan
from app.replay import replay
from app.schemas import OptimizeOut, ScenarioIn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gridwise")

app = FastAPI(title="GridWise", version="1.0.0", docs_url=None, redoc_url=None)


@app.exception_handler(RequestValidationError)
async def _malformed_request(_: Request, exc: RequestValidationError):
    """The specification asks for 400 on a structurally invalid request; 422 is optional.
    One consistent code keeps the contract simple.

    Only the field path and message are returned. pydantic puts the offending input
    in each error, which for a non-JSON body is raw bytes - not serializable, and not
    something to reflect back to a caller regardless.
    """
    detail = [
        {"loc": ".".join(str(p) for p in err.get("loc", ())), "msg": str(err.get("msg", ""))}
        for err in exc.errors()[:5]
    ]
    return JSONResponse(status_code=400, content={"error": "invalid request", "detail": detail})


@app.exception_handler(Exception)
async def _internal_error(_: Request, exc: Exception):
    """Controlled internal error. The client never sees a stack trace or configuration."""
    log.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "internal error"})


@app.get("/health")
def health():
    """Readiness probe. No external dependency - cheap under repeated polling."""
    return {"status": "ok"}


def _summarise(plan: List[Dict[str, Any]], directives: List[Dict[str, Any]],
               total_cost: float, dropped: List[int]) -> str:
    applied = [d for d in directives if d["directive_type"] != "no_op"]
    charge_hours = [r["hour"] for r in plan if r["battery_action"] == "charge"]
    discharge_hours = [r["hour"] for r in plan if r["battery_action"] == "discharge"]

    parts = []
    if applied:
        named = ", ".join(sorted({d["directive_type"] for d in applied}))
        parts.append(f"Applied operator directives: {named}.")
    else:
        parts.append("No operator note changed the schedule.")
    if charge_hours:
        parts.append(f"Charges the battery during {len(charge_hours)} low-tariff hours.")
    if discharge_hours:
        parts.append(f"Discharges across {len(discharge_hours)} higher-tariff hours.")
    parts.append("Battery returns to its initial level by the end of hour 23.")
    parts.append(f"Total grid cost {total_cost:.2f} BDT.")
    if dropped:
        parts.append(f"Notes {dropped} could not be satisfied together and were relaxed.")
    return " ".join(parts)


@app.post("/optimize-energy", response_model=OptimizeOut)
async def optimize_energy(scenario: ScenarioIn):
    battery = scenario.battery

    # 1. interpret - the only step that reads English. Never raises.
    directives, source = await interpret(
        scenario.operator_notes, battery.capacity_kwh, battery.minimum_energy_kwh)

    # 2. optimize against the validated directives
    try:
        raw, applied, dropped = solve(scenario.hours, battery, directives)
    except Infeasible:
        log.error("infeasible even with no directives; solving base scenario")
        raw, applied, dropped = solve(scenario.hours, battery, [])

    # 3. publishable rows and totals recomputed from those rows
    plan, total_grid, total_cost, peak_grid = build_plan(scenario.hours, battery, raw)

    # 4. self-check against the directives that were actually applied
    violations = replay(scenario.hours, battery, applied, plan)
    if violations:
        log.error("self-check failed (%s); falling back to a directive-free plan", violations[:3])
        raw, applied, dropped = solve(scenario.hours, battery, [])
        plan, total_grid, total_cost, peak_grid = build_plan(scenario.hours, battery, raw)

    log.info("scenario=%s source=%s notes=%d applied=%d cost=%.2f",
             scenario.scenario_id, source, len(directives), len(applied), total_cost)

    return {
        "scenario_id": scenario.scenario_id,
        "directive_interpretation": directives,
        "hourly_plan": plan,
        "total_grid_kwh": total_grid,
        "total_cost_bdt": total_cost,
        "peak_grid_kwh": peak_grid,
        "plan_summary": _summarise(plan, directives, total_cost, dropped),
    }
