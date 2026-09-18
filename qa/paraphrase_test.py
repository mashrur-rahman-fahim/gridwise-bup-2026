#!/usr/bin/env python3
"""
GridWise paraphrase + determinism probe.

Two things nothing else tests:

1. INVERTED PERCENTAGE WORDING.  Every existing paraphrase says how much solar
   REMAINS ("a quarter of forecast"). The judge's hidden notes may instead say
   how much is LOST ("output drops BY 75%"). Same directive, opposite number.
   An interpreter that returns 0.75 instead of 0.25 passes every current test
   and fails the hidden set.

2. DETERMINISM.  An LLM is stochastic. Running a note once proves nothing;
   90%-reliable and 100%-reliable look identical in a single pass.

Paraphrases are GENERATED from each case's ground truth, so all 10 cases are
covered - including SAMPLE-07/08/10, which no hand-written paraphrase reaches.

Run:
  py paraphrase_test.py --cases public_sample_cases.json --url https://gridwise.mashrurrahman.com
  py paraphrase_test.py ... --reps 3          # determinism (default 3)
  py paraphrase_test.py ... --case SAMPLE-09  # one case
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

TOL = 0.01


def clock(h):
    return f"{h:02d}:00"


def window(hours):
    """Ground-truth hours are start-inclusive / end-exclusive.
    [12,13] -> '12:00 and 14:00'. The service must give the hours back."""
    return clock(min(hours)), clock(max(hours) + 1)


def pct(x):
    return f"{round(x * 100)}%"


def phrase(directive, battery):
    """Build a natural-language note from a ground-truth directive.

    Deliberately worded UNLIKE the public samples: losses are stated as
    reductions, reserves as percentages of capacity, and the vocabulary is
    changed throughout.
    """
    t = directive["directive_type"]
    adj = directive.get("structured_adjustment") or {}
    hours = adj.get("hours", [])
    if not hours:
        return None
    a, b = window(hours)

    if t == "solar_reduction":
        f = adj["factor"]
        lost = pct(1 - f)
        # THE KEY CASE: stated as the loss, not the remainder
        return (f"Maintenance crews are on the array between {a} and {b}, "
                f"which will cut rooftop solar output by {lost} for that period.")

    if t == "minimum_battery_reserve":
        v = adj["minimum_energy_kwh"]
        cap = battery["capacity_kwh"]
        share = v / cap if cap else 0
        if abs(share * 100 - round(share * 100)) < 1e-6:
            amount = f"{pct(share)} of the pack's rated capacity"
        else:
            amount = f"{v} kWh"
        return (f"Emergency preparedness requires that no less than {amount} "
                f"stays in the battery between {a} and {b}.")

    if t == "no_charge_window":
        return (f"The charging circuit is being serviced between {a} and {b}, "
                f"so the pack cannot take any charge in that period.")

    if t == "no_discharge_window":
        return (f"Between {a} and {b} the battery is locked out of supplying "
                f"the site, so no discharge is permitted then.")

    if t == "max_grid_window":
        v = adj["max_grid_kwh"]
        return (f"Because of a temporary limit on the feeder, hourly import "
                f"from the grid must stay at or below {v} kWh between {a} and {b}.")

    return None


DISTRACTORS = [
    "The transport office has revised the shuttle timings for next semester.",
    "Alumni association dues can now be paid at the accounts desk.",
    "The seminar room projector was sent out for servicing yesterday.",
]


def build(case):
    """Return (notes, expected) or None if the case has no usable directive."""
    truth = case["expected_output"]["directive_interpretation"]
    battery = case["input"]["battery"]

    notes, expected = [], []
    d_i = 0
    for entry in truth:
        if entry["directive_type"] == "no_op":
            notes.append(DISTRACTORS[d_i % len(DISTRACTORS)])
            d_i += 1
            expected.append({"directive_type": "no_op"})
        else:
            text = phrase(entry, battery)
            if text is None:
                return None
            notes.append(text)
            exp = {"directive_type": entry["directive_type"]}
            exp.update(entry["structured_adjustment"])
            expected.append(exp)

    if not any(e["directive_type"] != "no_op" for e in expected):
        return None
    return notes, expected


def compare(got, expected):
    """Return a list of human-readable mismatches."""
    errs = []
    if not isinstance(got, list) or len(got) != len(expected):
        return [f"expected {len(expected)} entries, got "
                f"{len(got) if isinstance(got, list) else type(got).__name__}"]

    for i, (g, e) in enumerate(zip(got, expected)):
        tag = f"note {i}"
        if g.get("note_index") != i:
            errs.append(f"{tag}: note_index {g.get('note_index')}, want {i}")

        if g.get("directive_type") != e["directive_type"]:
            errs.append(f"{tag}: got {g.get('directive_type')!r}, "
                        f"want {e['directive_type']!r}  <-- paraphrase not recognised")
            continue

        if e["directive_type"] == "no_op":
            if g.get("applies") is not False:
                errs.append(f"{tag}: no_op must have applies=false")
            if g.get("structured_adjustment") is not None:
                errs.append(f"{tag}: no_op must have structured_adjustment=null")
            continue

        adj = g.get("structured_adjustment")
        if not isinstance(adj, dict):
            errs.append(f"{tag}: missing structured_adjustment")
            continue

        if adj.get("hours") != e.get("hours"):
            errs.append(f"{tag}: hours {adj.get('hours')} != {e.get('hours')}"
                        "  <-- end-exclusive window")

        for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
            if key in e:
                gv, ev = adj.get(key), e[key]
                if not isinstance(gv, (int, float)) or abs(gv - ev) > TOL:
                    hint = ""
                    if key == "factor" and isinstance(gv, (int, float)) \
                            and abs(gv - (1 - ev)) <= TOL:
                        hint = ("  <-- INVERTED! returned the fraction REMOVED, "
                                "not the fraction remaining")
                    errs.append(f"{tag}: {key} {gv!r} != {ev!r}{hint}")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--cases", default="public_sample_cases.json")
    ap.add_argument("--case", help="only this case id")
    ap.add_argument("--reps", type=int, default=3,
                    help="runs per case, for determinism (default 3)")
    args = ap.parse_args()

    endpoint = args.url.rstrip("/") + "/optimize-energy"
    cases = json.load(open(args.cases, encoding="utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            sys.exit(f"no case {args.case}")

    s = requests.Session()
    solid = flaky = broken = skipped = 0
    inverted_hits = []

    for case in cases:
        built = build(case)
        if built is None:
            skipped += 1
            continue
        notes, expected = built

        payload = json.loads(json.dumps(case["input"]))
        payload["operator_notes"] = notes

        runs = []
        for _ in range(args.reps):
            try:
                r = s.post(endpoint, json=payload, timeout=35)
                if r.status_code != 200:
                    runs.append(([f"HTTP {r.status_code}: {r.text[:120]}"], None))
                    continue
                got = r.json().get("directive_interpretation")
                runs.append((compare(got, expected), got))
            except Exception as e:
                runs.append(([f"request failed: {e}"], None))

        fails = [errs for errs, _ in runs if errs]
        fingerprints = {json.dumps(g, sort_keys=True) for _, g in runs if g is not None}
        stable = len(fingerprints) <= 1

        if not fails and stable:
            solid += 1
            print(f"[OK]      {case['id']}  {case['label']}"
                  f"   ({args.reps}/{args.reps} runs identical)")
        elif not fails and not stable:
            flaky += 1
            print(f"[UNSTABLE]{case['id']}  {case['label']}")
            print(f"          all runs correct, but output VARIED across "
                  f"{args.reps} runs - {len(fingerprints)} different answers")
        else:
            broken += 1
            n_bad = len(fails)
            state = ("every run" if n_bad == args.reps
                     else f"{n_bad} of {args.reps} runs  <-- INTERMITTENT")
            print(f"[FAIL]    {case['id']}  {case['label']}   ({state})")
            seen = set()
            for errs in fails:
                for e in errs:
                    if e not in seen:
                        seen.add(e)
                        print(f"          - {e}")
                        if "INVERTED" in e:
                            inverted_hits.append(case["id"])
        for n in notes:
            print(f"            note: {n[:96]}")
        print()

    total = solid + flaky + broken
    print("=" * 66)
    print(f"stable & correct   {solid}/{total}")
    print(f"correct but flaky  {flaky}/{total}")
    print(f"wrong              {broken}/{total}")
    if skipped:
        print(f"skipped            {skipped} (no directive to paraphrase)")
    if inverted_hits:
        print()
        print("!! INVERTED FACTOR CONFIRMED in: " + ", ".join(sorted(set(inverted_hits))))
        print("   The interpreter returns the fraction REMOVED where the spec")
        print("   wants the fraction REMAINING. Fix the prompt:")
        print('   "an 80% reduction means factor = 0.2, not 0.8"')
    if flaky:
        print()
        print("!! Output varied between identical requests. A single green run")
        print("   does not mean the interpreter is reliable on hidden cases.")
    print("=" * 66)
    sys.exit(1 if (broken or flaky) else 0)


if __name__ == "__main__":
    main()
