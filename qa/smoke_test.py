#!/usr/bin/env python3
"""
GridWise contract + reliability smoke test.

validate.py checks whether plans are CORRECT.
This checks whether the service BEHAVES - the other 20 rubric points:
API Contract & Schema, Performance & Reliability.

Run:  python3 smoke_test.py --url https://your-service.onrender.com
"""

import argparse
import concurrent.futures as cf
import json
import re
import statistics
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

CASES_FILE = "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

# things that must never appear in a response body
SECRET_PATTERNS = [
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google API key"),
    (r"sk-[A-Za-z0-9_\-]{20,}", "OpenAI-style key"),
    (r"gsk_[A-Za-z0-9]{20,}", "Groq key"),
    (r"ghp_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"xoxb-[A-Za-z0-9\-]{20,}", "Slack token"),
    (r"Traceback \(most recent call last\)", "Python traceback"),
    (r'"(api_?key|secret|token|password)"\s*:', "credential field"),
]

results = []


def record(name, ok, detail="", fatal=False):
    results.append((name, ok, detail, fatal))
    mark = "PASS" if ok else ("FAIL" if fatal else "WARN")
    print(f"  [{mark}] {name}" + (f"  - {detail}" if detail else ""))


def scan_secrets(text, where):
    for pat, label in SECRET_PATTERNS:
        if re.search(pat, text):
            record(f"no secrets in {where}", False, f"found {label}", fatal=True)
            return
    record(f"no secrets in {where}", True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--cases", default=CASES_FILE)
    ap.add_argument("--reps", type=int, default=6,
                    help="repeat calls for the latency sample")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    health = base + "/health"
    opt = base + "/optimize-energy"
    s = requests.Session()

    cases = json.load(open(args.cases, encoding="utf-8"))["cases"]
    good = cases[0]["input"]

    # ---------------------------------------------------------- health
    print("\nHEALTH")
    try:
        t0 = time.perf_counter()
        r = s.get(health, timeout=20)
        dt = time.perf_counter() - t0
        record("GET /health returns 200", r.status_code == 200,
               f"got {r.status_code}", fatal=True)
        try:
            body = r.json()
            record('body is {"status":"ok"}', body.get("status") == "ok",
                   json.dumps(body)[:60], fatal=True)
        except ValueError:
            record("health body is JSON", False, r.text[:60], fatal=True)
        record("health responds under 5s", dt < 5, f"{dt:.2f}s")
    except Exception as e:
        record("GET /health reachable", False, str(e)[:80], fatal=True)
        summary()
        return

    # ---------------------------------------------------------- happy path
    print("\nHAPPY PATH")
    t0 = time.perf_counter()
    r = s.post(opt, json=good, timeout=35)
    dt = time.perf_counter() - t0
    record("valid request returns 200", r.status_code == 200,
           f"got {r.status_code}", fatal=True)
    record("finishes inside the 30s limit", dt < 30, f"{dt:.2f}s", fatal=True)
    record("finishes inside 5s (full latency points)", dt < 5, f"{dt:.2f}s")

    body_text = r.text
    scan_secrets(body_text, "response body")
    try:
        first = r.json()
        record("response is JSON", True)
    except ValueError:
        record("response is JSON", False, body_text[:80], fatal=True)
        summary()
        return

    record("content-type is application/json",
           "application/json" in r.headers.get("content-type", ""),
           r.headers.get("content-type", "none"))

    # ---------------------------------------------------------- bad input
    print("\nBAD INPUT (must not 5xx)")

    def expect_4xx(name, **kw):
        try:
            rr = s.post(opt, timeout=35, **kw)
        except Exception as e:
            record(name, False, str(e)[:60], fatal=True)
            return
        ok = 400 <= rr.status_code < 500
        record(name, ok, f"got {rr.status_code}", fatal=not ok)
        if rr.status_code >= 500:
            scan_secrets(rr.text, f"{name} error body")

    expect_4xx("malformed JSON -> 4xx",
               data="{not json at all",
               headers={"Content-Type": "application/json"})

    expect_4xx("empty body -> 4xx",
               data="", headers={"Content-Type": "application/json"})

    bad = json.loads(json.dumps(good))
    del bad["battery"]
    expect_4xx("missing battery -> 4xx", json=bad)

    bad = json.loads(json.dumps(good))
    bad["hours"] = bad["hours"][:10]
    expect_4xx("only 10 hours -> 4xx", json=bad)

    bad = json.loads(json.dumps(good))
    bad["operator_notes"] = []
    expect_4xx("empty operator_notes -> 4xx", json=bad)

    bad = json.loads(json.dumps(good))
    bad["hours"][0]["demand_kwh"] = "lots"
    expect_4xx("wrong type for demand -> 4xx", json=bad)

    # ---------------------------------------------------------- robustness
    print("\nROBUSTNESS")

    # a note that is pure noise - must not crash, must not invent a directive
    odd = json.loads(json.dumps(good))
    odd["operator_notes"] = ["asdkjh qwe 9999 ;;; বাংলা লেখা"]
    try:
        rr = s.post(opt, json=odd, timeout=35)
        record("nonsense note still returns 200", rr.status_code == 200,
               f"got {rr.status_code}", fatal=True)
        if rr.status_code == 200:
            di = rr.json().get("directive_interpretation", [])
            record("nonsense note -> exactly 1 entry", len(di) == 1, f"got {len(di)}")
    except Exception as e:
        record("nonsense note handled", False, str(e)[:60], fatal=True)

    # max notes
    three = json.loads(json.dumps(good))
    three["operator_notes"] = [
        "Solar panels will be cleaned from 10 AM to 12 PM, output about 30% of forecast.",
        "Do not charge the battery between 1 PM and 4 PM.",
        "Cafeteria menu changes next week.",
    ]
    try:
        rr = s.post(opt, json=three, timeout=35)
        record("3 notes returns 200", rr.status_code == 200, f"got {rr.status_code}")
        if rr.status_code == 200:
            di = rr.json().get("directive_interpretation", [])
            record("3 notes -> 3 entries", len(di) == 3, f"got {len(di)}")
            idx = [e.get("note_index") for e in di]
            record("note_index is 0,1,2", idx == [0, 1, 2], str(idx))
            if len(di) == 3:
                record("third note recognised as no_op",
                       di[2].get("directive_type") == "no_op",
                       f"got {di[2].get('directive_type')}")
    except Exception as e:
        record("3 notes handled", False, str(e)[:60])

    # determinism - same input twice should give the same cost
    try:
        r2 = s.post(opt, json=good, timeout=35)
        if r2.status_code == 200:
            c1 = first.get("total_cost_bdt")
            c2 = r2.json().get("total_cost_bdt")
            same = isinstance(c1, (int, float)) and isinstance(c2, (int, float)) \
                and abs(c1 - c2) <= 0.01
            record("same input -> same cost", same, f"{c1} vs {c2}")
    except Exception as e:
        record("repeat request", False, str(e)[:60])

    # ---------------------------------------------------------- load
    print("\nLOAD")
    inputs = [c["input"] for c in cases]
    try:
        t0 = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(requests.post, opt, json=i, timeout=35)
                    for i in inputs[:5]]
            codes = [f.result().status_code for f in futs]
        wall = time.perf_counter() - t0
        record("5 concurrent requests all 200",
               all(c == 200 for c in codes), str(codes), fatal=True)
        record("5 concurrent finish under 30s", wall < 30, f"{wall:.2f}s")
    except Exception as e:
        record("concurrent requests", False, str(e)[:80], fatal=True)

    # latency sample
    times = []
    for i in range(args.reps):
        payload = inputs[i % len(inputs)]
        t0 = time.perf_counter()
        try:
            rr = s.post(opt, json=payload, timeout=35)
            times.append(time.perf_counter() - t0)
        except Exception:
            times.append(35.0)
    if times:
        times_sorted = sorted(times)
        p95 = (statistics.quantiles(times, n=20)[-1]
               if len(times) >= 3 else times_sorted[-1])
        band = ("3/3" if p95 <= 5 else "2/3" if p95 <= 15
                else "1/3" if p95 <= 30 else "0/3")
        print(f"\n  latency  n={len(times)}  "
              f"median {statistics.median(times):.2f}s  "
              f"max {max(times):.2f}s  p95 {p95:.2f}s  -> {band} points")
        record("p95 under 30s (no failure penalty)", p95 <= 30, f"{p95:.2f}s",
               fatal=p95 > 30)

    summary()


def summary():
    fails = [r for r in results if not r[1] and r[3]]
    warns = [r for r in results if not r[1] and not r[3]]
    print()
    print("=" * 62)
    print(f"checks {len(results)}   passed {sum(1 for r in results if r[1])}"
          f"   failed {len(fails)}   warnings {len(warns)}")
    if fails:
        print("\nMUST FIX:")
        for n, _, d, _ in fails:
            print(f"  - {n}  ({d})")
    if warns:
        print("\nPOINTS AT RISK:")
        for n, _, d, _ in warns:
            print(f"  - {n}  ({d})")
    print("=" * 62)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
