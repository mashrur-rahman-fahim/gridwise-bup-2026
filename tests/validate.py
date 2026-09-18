#!/usr/bin/env python3
"""
GridWise public-case validator.

Replays every returned hourly_plan the same way the official judge does:
against the ORGANIZER GROUND-TRUTH directives from expected_output,
not against whatever the team's own interpretation claimed.

Usage
-----
  # test a running service
  python validate.py --url https://your-service.onrender.com

  # sanity-check the validator itself against the reference plans
  # (no service needed - should print 10/10 PASS)
  python validate.py --self-test

  # one case only
  python validate.py --url http://localhost:8000 --case SAMPLE-03

Requires: requests  (pip install requests)
"""

import argparse
import json
import statistics
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("pip install requests")


TOL = 0.01
DEFAULT_CASES = "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

PLAN_FIELDS = [
    "hour",
    "grid_kwh",
    "solar_used_kwh",
    "battery_action",
    "battery_kwh",
    "battery_energy_after_kwh",
]

TOP_FIELDS = [
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary",
]


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def num(x):
    """True if x is a real, finite number (bool is not a number here)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return x == x and abs(x) != float("inf")


# ----------------------------------------------------------------------
# Ground truth
# ----------------------------------------------------------------------

def build_directives(interpretation):
    """Turn a directive_interpretation array into replay constraints."""
    d = {
        "solar_factor": {},   # hour -> factor
        "reserve": {},        # hour -> minimum energy
        "no_charge": set(),
        "no_discharge": set(),
        "grid_cap": {},       # hour -> cap
    }
    for e in interpretation:
        t = e.get("directive_type")
        adj = e.get("structured_adjustment")
        if t == "no_op" or not adj:
            continue
        hours = adj.get("hours", []) or []
        if t == "solar_reduction":
            for h in hours:
                d["solar_factor"][h] = adj.get("factor")
        elif t == "minimum_battery_reserve":
            v = adj.get("minimum_energy_kwh")
            for h in hours:
                d["reserve"][h] = max(d["reserve"].get(h, 0.0), v)
        elif t == "no_charge_window":
            d["no_charge"].update(hours)
        elif t == "no_discharge_window":
            d["no_discharge"].update(hours)
        elif t == "max_grid_window":
            v = adj.get("max_grid_kwh")
            for h in hours:
                d["grid_cap"][h] = min(d["grid_cap"].get(h, float("inf")), v)
    return d


# ----------------------------------------------------------------------
# Schema checks
# ----------------------------------------------------------------------

def check_schema(resp, case_input, errs):
    if not isinstance(resp, dict):
        errs.append("response is not a JSON object")
        return False

    for f in TOP_FIELDS:
        if f not in resp:
            errs.append(f"missing top-level field: {f}")

    if resp.get("scenario_id") != case_input["scenario_id"]:
        errs.append(
            f"scenario_id echo wrong: got {resp.get('scenario_id')!r}, "
            f"want {case_input['scenario_id']!r}"
        )

    plan = resp.get("hourly_plan")
    if not isinstance(plan, list):
        errs.append("hourly_plan is not a list")
        return False
    if len(plan) != 24:
        errs.append(f"hourly_plan has {len(plan)} entries, want 24")
        return False

    hours = []
    for i, p in enumerate(plan):
        if not isinstance(p, dict):
            errs.append(f"hourly_plan[{i}] is not an object")
            return False
        for f in PLAN_FIELDS:
            if f not in p:
                errs.append(f"hour entry {i} missing field: {f}")
        hours.append(p.get("hour"))

    if sorted(h for h in hours if isinstance(h, int)) != list(range(24)):
        errs.append(f"hourly_plan hours are not exactly 0..23 unique: {hours}")
        return False

    return len(errs) == 0


def check_interpretation(resp, case, errs, warns):
    """Compare against organizer ground truth.

    Returns (notes_exactly_right, notes_total) so the caller can score the
    interpretation bucket separately from plan validity.
    """
    got = resp.get("directive_interpretation")
    want = case["expected_output"]["directive_interpretation"]
    n_notes = len(case["input"]["operator_notes"])

    if not isinstance(got, list):
        errs.append("directive_interpretation is not a list")
        return 0, n_notes
    if len(got) != n_notes:
        errs.append(
            f"directive_interpretation has {len(got)} entries, "
            f"want {n_notes} (one per operator note)"
        )
        return 0, n_notes

    right = 0

    for i, (g, w) in enumerate(zip(got, want)):
        tag = f"note {i}"
        before = len(errs)

        if g.get("note_index") != i:
            errs.append(f"{tag}: note_index is {g.get('note_index')}, want {i} (ascending order)")

        dt = g.get("directive_type")
        if dt not in DIRECTIVE_TYPES:
            errs.append(f"{tag}: unsupported directive_type {dt!r}")
            continue  # counted wrong: `before` never matched

        applies = g.get("applies")
        adj = g.get("structured_adjustment")

        # applies / no_op semantics
        if dt == "no_op":
            if applies is not False:
                errs.append(f"{tag}: no_op must have applies=false, got {applies!r}")
            if adj is not None:
                errs.append(f"{tag}: no_op must have structured_adjustment=null")
        else:
            if applies is not True:
                errs.append(f"{tag}: {dt} must have applies=true, got {applies!r}")
            if not isinstance(adj, dict):
                errs.append(f"{tag}: {dt} needs a structured_adjustment object")
                continue

            hrs = adj.get("hours")
            if not isinstance(hrs, list) or not hrs:
                errs.append(f"{tag}: hours must be a non-empty list")
            else:
                if any(not isinstance(h, int) or isinstance(h, bool) or not 0 <= h <= 23 for h in hrs):
                    errs.append(f"{tag}: hours must be integers 0-23, got {hrs}")
                if hrs != sorted(set(hrs)):
                    errs.append(f"{tag}: hours must be unique and ascending, got {hrs}")

            if dt == "solar_reduction":
                f = adj.get("factor")
                if not num(f) or not 0 <= f <= 1:
                    errs.append(f"{tag}: factor must be a number in [0,1], got {f!r}")
            elif dt == "minimum_battery_reserve":
                v = adj.get("minimum_energy_kwh")
                cap = case["input"]["battery"]["capacity_kwh"]
                if not num(v) or v < 0 or v > cap:
                    errs.append(f"{tag}: minimum_energy_kwh out of range, got {v!r}")
            elif dt == "max_grid_window":
                v = adj.get("max_grid_kwh")
                if not num(v) or v < 0:
                    errs.append(f"{tag}: max_grid_kwh must be >= 0, got {v!r}")

        # --- compare to ground truth (interpretation score) ---
        if dt != w["directive_type"]:
            errs.append(
                f"{tag}: directive_type is {dt!r}, ground truth is {w['directive_type']!r}"
            )
            continue
        if applies != w["applies"]:
            errs.append(f"{tag}: applies is {applies!r}, ground truth is {w['applies']!r}")

        wadj = w.get("structured_adjustment")
        if wadj is not None and isinstance(adj, dict):
            if adj.get("hours") != wadj.get("hours"):
                errs.append(
                    f"{tag}: hours {adj.get('hours')} != ground truth {wadj.get('hours')}"
                    "   <-- check end-exclusive windows"
                )
            for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
                if key in wadj:
                    gv, wv = adj.get(key), wadj[key]
                    if not num(gv) or not close(gv, wv):
                        hint = ("   <-- factor = fraction REMAINING"
                                if key == "factor" else "")
                        errs.append(
                            f"{tag}: {key} {gv!r} != ground truth {wv!r}{hint}")

        if len(errs) == before:
            right += 1

    return right, n_notes


# ----------------------------------------------------------------------
# Replay
# ----------------------------------------------------------------------

def replay(resp, case, errs):
    """Walk the plan hour by hour under ground-truth directives."""
    inp = case["input"]
    bat = inp["battery"]
    hours = {h["hour"]: h for h in inp["hours"]}
    gt = build_directives(case["expected_output"]["directive_interpretation"])

    plan = {p["hour"]: p for p in resp["hourly_plan"]}

    energy = float(bat["initial_energy_kwh"])
    total_grid = 0.0
    total_cost = 0.0
    peak = 0.0

    for h in range(24):
        p = plan[h]
        src = hours[h]
        tag = f"hour {h}"

        grid = p.get("grid_kwh")
        solar = p.get("solar_used_kwh")
        action = p.get("battery_action")
        amount = p.get("battery_kwh")
        after = p.get("battery_energy_after_kwh")

        if not all(num(v) for v in (grid, solar, amount, after)):
            errs.append(f"{tag}: non-numeric or infinite value in plan entry")
            return None
        if grid < -TOL or solar < -TOL or amount < -TOL or after < -TOL:
            errs.append(f"{tag}: negative value (grid={grid}, solar={solar}, battery={amount})")
        if action not in ("charge", "discharge", "idle"):
            errs.append(f"{tag}: battery_action {action!r} not in charge/discharge/idle")
            return None

        # effective solar after ground-truth reduction
        eff = float(src["solar_kwh"])
        if h in gt["solar_factor"]:
            eff *= gt["solar_factor"][h]
        if solar > eff + TOL:
            errs.append(f"{tag}: solar_used {solar} exceeds effective solar {eff:.2f}")

        # split the action
        charge = amount if action == "charge" else 0.0
        discharge = amount if action == "discharge" else 0.0
        if action == "idle" and abs(amount) > TOL:
            errs.append(f"{tag}: idle must have battery_kwh = 0, got {amount}")

        # rate limits
        if charge > bat["max_charge_kwh_per_hour"] + TOL:
            errs.append(
                f"{tag}: charge {charge} exceeds limit {bat['max_charge_kwh_per_hour']}"
            )
        if discharge > bat["max_discharge_kwh_per_hour"] + TOL:
            errs.append(
                f"{tag}: discharge {discharge} exceeds limit {bat['max_discharge_kwh_per_hour']}"
            )

        # directive windows
        if h in gt["no_charge"] and charge > TOL:
            errs.append(f"{tag}: charging {charge} inside no_charge_window")
        if h in gt["no_discharge"] and discharge > TOL:
            errs.append(f"{tag}: discharging {discharge} inside no_discharge_window")
        if h in gt["grid_cap"] and grid > gt["grid_cap"][h] + TOL:
            errs.append(f"{tag}: grid {grid} exceeds cap {gt['grid_cap'][h]}")

        # energy balance
        lhs = grid + solar + discharge
        rhs = float(src["demand_kwh"]) + charge
        if not close(lhs, rhs):
            errs.append(
                f"{tag}: energy balance off by {lhs - rhs:+.3f}  "
                f"(grid {grid} + solar {solar} + discharge {discharge} "
                f"!= demand {src['demand_kwh']} + charge {charge})"
            )

        # battery state continuity
        energy = energy + charge - discharge
        if not close(energy, after):
            errs.append(
                f"{tag}: battery_energy_after {after} does not follow from the action "
                f"(expected {energy:.3f})"
            )
            energy = float(after)  # keep walking from what they reported

        # bounds
        floor = max(float(bat["minimum_energy_kwh"]), gt["reserve"].get(h, 0.0))
        if energy < floor - TOL:
            errs.append(f"{tag}: battery {energy:.2f} below required minimum {floor}")
        if energy > bat["capacity_kwh"] + TOL:
            errs.append(f"{tag}: battery {energy:.2f} above capacity {bat['capacity_kwh']}")

        total_grid += grid
        total_cost += grid * float(src["tariff_bdt_per_kwh"])
        peak = max(peak, grid)

    # end-of-day neutrality
    if not close(energy, float(bat["initial_energy_kwh"])):
        errs.append(
            f"END OF DAY: battery {energy:.3f} != initial {bat['initial_energy_kwh']}"
            "   <-- neutrality violated"
        )

    # reported totals must match recomputation
    for name, calc in (
        ("total_grid_kwh", total_grid),
        ("total_cost_bdt", total_cost),
        ("peak_grid_kwh", peak),
    ):
        rep = resp.get(name)
        if not num(rep):
            errs.append(f"{name} is not a number: {rep!r}")
        elif not close(rep, calc):
            errs.append(f"{name} reported {rep} but recomputes to {calc:.3f}")

    return total_cost


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------

class Result:
    """One case's outcome, split the way the rubric scores it."""

    def __init__(self):
        self.interp_errs = []   # LLM Directive Interpretation (25 pts)
        self.plan_errs = []     # Directive Application & Constraints (25 pts)
        self.warns = []
        self.elapsed = 0.0
        self.cost = None
        self.notes_right = 0
        self.notes_total = 0

    @property
    def plan_valid(self):
        return not self.plan_errs and self.cost is not None

    @property
    def all_errs(self):
        return self.plan_errs + self.interp_errs


def run_case(case, url, session, self_test):
    res = Result()
    res.notes_total = len(case["input"]["operator_notes"])

    if self_test:
        resp = case["expected_output"]
    else:
        endpoint = url.rstrip("/") + "/optimize-energy"
        t0 = time.perf_counter()
        try:
            r = session.post(endpoint, json=case["input"], timeout=35)
            res.elapsed = time.perf_counter() - t0
        except requests.exceptions.Timeout:
            res.elapsed = 999.0
            res.plan_errs.append("request timed out (>35s) - judge counts a failure")
            return res
        except Exception as e:
            res.plan_errs.append(f"request failed: {e}")
            return res

        if r.status_code != 200:
            res.plan_errs.append(f"HTTP {r.status_code} (want 200): {r.text[:200]}")
            return res
        try:
            resp = r.json()
        except ValueError:
            res.plan_errs.append("response is not valid JSON")
            return res

        if res.elapsed > 30:
            res.plan_errs.append(
                f"took {res.elapsed:.1f}s - over the 30s per-request limit")
        elif res.elapsed > 5:
            res.warns.append(
                f"took {res.elapsed:.1f}s - over 5s costs latency points")

    if not check_schema(resp, case["input"], res.plan_errs):
        return res

    res.notes_right, res.notes_total = check_interpretation(
        resp, case, res.interp_errs, res.warns)
    res.cost = replay(resp, case, res.plan_errs)

    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="base URL of the deployed service")
    ap.add_argument("--cases", default=DEFAULT_CASES, help="public sample cases JSON")
    ap.add_argument("--case", help="run only this case id, e.g. SAMPLE-03")
    ap.add_argument("--self-test", action="store_true",
                    help="validate the reference plans instead of calling a service")
    ap.add_argument("-v", "--verbose", action="store_true", help="show warnings too")
    args = ap.parse_args()

    if not args.url and not args.self_test:
        ap.error("give --url, or use --self-test")

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            sys.exit(f"no case with id {args.case}")

    session = requests.Session()

    # health check
    if args.url:
        try:
            r = session.get(args.url.rstrip("/") + "/health", timeout=15)
            body = r.json() if r.ok else {}
            ok = r.status_code == 200 and body.get("status") == "ok"
            print(f"/health  {'PASS' if ok else 'FAIL'}  "
                  f"[{r.status_code}] {json.dumps(body)[:80]}")
        except Exception as e:
            print(f"/health  FAIL  {e}")
        print()

    valid = 0
    ratios = []
    times = []
    notes_right = notes_total = 0

    for case in cases:
        res = run_case(case, args.url, session, args.self_test)
        ref = case["expected_output"]["total_cost_bdt"]

        if res.elapsed:
            times.append(res.elapsed)
        notes_right += res.notes_right
        notes_total += res.notes_total

        # a case can have a perfectly valid plan but a wrong reading of the
        # note, or the reverse - the rubric scores those separately, so the
        # report keeps them apart.
        if res.plan_valid:
            valid += 1
            ratio = min(1.0, ref / res.cost) if res.cost > TOL else 1.0
            ratios.append(ratio)
            gap = (res.cost - ref) / ref * 100 if ref else 0.0
            label = "OK" if not res.interp_errs else "PLAN OK / INTERP WRONG"
            print(f"[{label}] {case['id']}  {case['label']}")
            print(f"       cost {res.cost:,.2f} vs reference {ref:,.2f}"
                  f"   quality {ratio:.4f}"
                  + ("" if gap <= 0.01 else f"   +{gap:.2f}% over reference"))
            if gap < -0.01:
                print("       cost BELOW reference - a constraint is probably missing")
        else:
            ratios.append(0.0)
            print(f"[INVALID] {case['id']}  {case['label']}"
                  "   (plan rejected -> 0 optimization credit)")
            for e in res.plan_errs[:8]:
                print(f"       P {e}")
            if len(res.plan_errs) > 8:
                print(f"       P ... and {len(res.plan_errs) - 8} more")

        for e in res.interp_errs[:6]:
            print(f"       I {e}")
        if len(res.interp_errs) > 6:
            print(f"       I ... and {len(res.interp_errs) - 6} more")

        if res.warns and (args.verbose or res.plan_valid):
            for w in res.warns:
                print(f"       ! {w}")
        print()

    # ---------------------------------------------------------- summary
    n = len(cases)
    print("=" * 62)
    print("  P = plan/constraint error (kills the case)")
    print("  I = interpretation error (costs interpretation points only)")
    print("-" * 62)

    interp_pct = notes_right / notes_total if notes_total else 0.0
    print(f"interpretation   {notes_right}/{notes_total} notes exact"
          f"      ~{interp_pct * 25:.1f} / 25")
    print(f"plan validity    {valid}/{n} cases valid"
          f"        ~{valid / n * 25:.1f} / 25")
    if ratios:
        avg = sum(ratios) / len(ratios)
        print(f"optimization     avg quality {avg:.4f}"
              f"         {avg * 10:.2f} / 10")
    if times:
        p95 = (statistics.quantiles(times, n=20)[-1] if len(times) >= 3
               else max(times))
        band = ("3/3" if p95 <= 5 else "2/3" if p95 <= 15
                else "1/3" if p95 <= 30 else "0/3")
        print(f"latency          p95 {p95:.2f}s"
              f"              {band} of the latency points")
    print("=" * 62)
    print("(approximate - the real judge weights notes and cases its own way)")

    sys.exit(0 if valid == n and notes_right == notes_total else 1)


if __name__ == "__main__":
    main()
