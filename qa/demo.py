#!/usr/bin/env python3
"""
GridWise live demo — one request, screen-recordable output for the video.

Sends one scenario to a deployed GridWise instance and prints the pipeline
in five slow, readable, numbered sections: the operator's notes, the request
sent, what the LLM understood, only the hours the directive actually changed,
and the resulting schedule totals. No raw JSON dump.

Usage
-----
  py demo.py --url https://your-service.onrender.com
  py demo.py --url https://your-service.onrender.com --case SAMPLE-03
  py demo.py --url https://your-service.onrender.com --pause 0
  py demo.py --url https://your-service.onrender.com \
      --note "Panels get washed 10 AM to 1 PM, output drops by 70% during that time."

Requires: requests  (pip install requests)
"""
import argparse
import json
import sys
import textwrap
import time

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

WIDTH = 78
WRAP = 74


def banner(n, title):
    print()
    print("=" * WIDTH)
    print(f"  {n}. {title}")
    print("=" * WIDTH)


def wrapped(text, indent=""):
    for line in textwrap.wrap(text, WRAP, initial_indent=indent, subsequent_indent=indent):
        print(line)


def pause(seconds):
    if seconds > 0:
        time.sleep(seconds)


def section_1(notes, seconds):
    banner(1, "WHAT THE OPERATOR WROTE")
    print()
    for i, note in enumerate(notes):
        wrapped(f'note {i}: "{note}"')
        print()
    pause(seconds)


def section_2(url, scenario, seconds):
    banner(2, "SENDING TO THE API")
    print()
    endpoint = url.rstrip("/") + "/optimize-energy"
    print(f"  POST {endpoint}")
    print()
    hours = scenario["hours"]
    battery = scenario["battery"]
    demand_total = sum(h["demand_kwh"] for h in hours)
    solar_total = sum(h["solar_kwh"] for h in hours)
    tariff_lo = min(h["tariff_bdt_per_kwh"] for h in hours)
    tariff_hi = max(h["tariff_bdt_per_kwh"] for h in hours)
    print(f"  24 hours of demand (total {demand_total:,.0f} kWh), "
          f"solar (total {solar_total:,.0f} kWh), "
          f"tariff ({tariff_lo:g}-{tariff_hi:g} BDT/kWh)")
    print(f"  battery capacity {battery['capacity_kwh']:g} kWh, "
          f"starting at {battery['initial_energy_kwh']:g} kWh")
    print()
    pause(seconds)

    t0 = time.perf_counter()
    resp = requests.post(endpoint, json=scenario, timeout=35)
    elapsed = time.perf_counter() - t0

    print(f"  status: {resp.status_code}      elapsed: {elapsed:.2f}s")
    pause(seconds)
    resp.raise_for_status()
    return resp.json()


def section_3(body, notes, seconds):
    banner(3, "WHAT THE LLM UNDERSTOOD")
    print()
    changed_hours = set()
    interp = body.get("directive_interpretation", [])

    for i, entry in enumerate(interp):
        dtype = entry.get("directive_type")
        print(f"  note {i}  ->  {dtype}")

        if dtype == "no_op" or not entry.get("applies"):
            print("      not relevant to today's schedule")
            print()
            continue

        adj = entry.get("structured_adjustment") or {}
        hrs = adj.get("hours", [])
        if hrs:
            changed_hours.update(hrs)
            print(f"      hours: {hrs}")
        for key, label in (("factor", "factor"),
                            ("minimum_energy_kwh", "minimum_energy_kwh"),
                            ("max_grid_kwh", "max_grid_kwh")):
            if key in adj:
                print(f"      {label}: {adj[key]}")

        explanation = entry.get("explanation", "")
        if explanation:
            wrapped(explanation, indent="      ")
        print()
        pause(seconds)

    return sorted(changed_hours)


def section_4(body, scenario, changed_hours, seconds):
    banner(4, "THE HOURS THE DIRECTIVE CHANGED")
    print()
    show_hours = changed_hours if changed_hours else list(range(8, 14))
    if not changed_hours:
        print("  (no directive changed any hour — showing hours 8-13)")
        print()

    hours_by_h = {h["hour"]: h for h in scenario["hours"]}
    plan_by_h = {p["hour"]: p for p in body.get("hourly_plan", [])}

    header = f"  {'hr':>3}  {'demand':>7}  {'solar':>7}  {'used':>7}  {'grid':>7}  {'battery':>16}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for h in show_hours:
        src = hours_by_h.get(h, {})
        p = plan_by_h.get(h, {})
        action = p.get("battery_action", "")
        amount = p.get("battery_kwh", 0)
        batt = "" if action == "idle" else f"{action} {amount:g}"
        print(f"  {h:>3}  {src.get('demand_kwh', 0):>7.1f}  {src.get('solar_kwh', 0):>7.1f}  "
              f"{p.get('solar_used_kwh', 0):>7.1f}  {p.get('grid_kwh', 0):>7.1f}  {batt:>16}")
    print()
    pause(seconds)


def section_5(body, scenario, seconds):
    banner(5, "THE RESULT")
    print()
    print(f"  total_cost_bdt   {body.get('total_cost_bdt'):,.2f} BDT")
    print(f"  total_grid_kwh   {body.get('total_grid_kwh'):,.2f} kWh")
    print(f"  peak_grid_kwh    {body.get('peak_grid_kwh'):,.2f} kWh")
    print()

    plan = body.get("hourly_plan", [])
    by_h = {p["hour"]: p for p in plan}
    start = scenario["battery"]["initial_energy_kwh"]
    end = by_h.get(23, {}).get("battery_energy_after_kwh")
    print(f"  battery at start   {start:g} kWh")
    print(f"  battery at hour 23 {end:g} kWh")
    if end is not None and abs(end - start) <= 0.01:
        print("  -> returned to exactly where it began")
    print()

    summary = body.get("plan_summary", "")
    if summary:
        wrapped(summary, indent="  ")
    print()
    pause(seconds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--cases", default="public_sample_cases.json")
    ap.add_argument("--case", default="SAMPLE-01")
    ap.add_argument("--note", action="append", dest="notes",
                     help="repeatable; replaces operator_notes entirely")
    ap.add_argument("--pause", type=float, default=1.2,
                     help="seconds between sections (default 1.2)")
    args = ap.parse_args()

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    case = next((c for c in cases if c["id"] == args.case), None)
    if case is None:
        sys.exit(f"no case with id {args.case}")

    scenario = json.loads(json.dumps(case["input"]))
    if args.notes:
        scenario["operator_notes"] = args.notes

    section_1(scenario["operator_notes"], args.pause)
    body = section_2(args.url, scenario, args.pause)
    changed_hours = section_3(body, scenario["operator_notes"], args.pause)
    section_4(body, scenario, changed_hours, args.pause)
    section_5(body, scenario, args.pause)


if __name__ == "__main__":
    main()
