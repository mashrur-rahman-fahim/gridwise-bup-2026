"""
Black-box live-endpoint test. Simulates what the judge harness does.

Deliberately imports NOTHING from app/ — it re-derives every check from the
Problem Statement so it cannot inherit a bug from the implementation.

Usage
-----
    GRIDWISE_URL=https://gridwise.mashrurrahman.com pytest tests/test_live_endpoint.py -v
    GRIDWISE_URL=http://localhost:8000              pytest tests/test_live_endpoint.py -v

Skips entirely when GRIDWISE_URL is unset, so it never breaks CI.
"""
import json, os, time, urllib.request, urllib.error
from pathlib import Path

import pytest

TOL = 0.01                      # PS 11.5 - absolute tolerance, kWh and BDT
TIMEOUT = 30                    # PG 08  - per-request hard limit
P95_TARGET = 5.0                # PG 08  - p95 <= 5s earns full latency points

BASE = os.environ.get("GRIDWISE_URL", "").rstrip("/")
HERE = Path(__file__).parent
PAYLOAD = json.loads((HERE / "payloads" / "live_scenario_01.json").read_text())
EXPECT = json.loads((HERE / "payloads" / "live_scenario_01.expected.json").read_text())

pytestmark = pytest.mark.skipif(not BASE, reason="set GRIDWISE_URL to run live tests")


# ----------------------------------------------------------------- helpers
def _post(path, payload, timeout=TIMEOUT):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"_raw": raw[:400].decode(errors="replace")}
        return e.code, parsed, time.perf_counter() - t0


def _post_raw(path, raw_bytes, content_type="application/json"):
    req = urllib.request.Request(
        f"{BASE}{path}", data=raw_bytes, headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture(scope="module")
def response():
    status, body, elapsed = _post("/optimize-energy", PAYLOAD)
    assert status == 200, f"expected 200, got {status}: {body}"
    return body


# ----------------------------------------------------------------- health
def test_health_returns_ok():
    """PS 6.2 - GET /health returns {"status":"ok"}."""
    with urllib.request.urlopen(f"{BASE}/health", timeout=TIMEOUT) as r:
        assert r.status == 200
        body = json.loads(r.read())
    assert body.get("status") == "ok", f"health body was {body}"


# ----------------------------------------------------------------- schema
def test_top_level_schema(response):
    """PS 10.1 - all seven top-level fields present, scenario_id echoed."""
    for field in ("scenario_id", "directive_interpretation", "hourly_plan",
                  "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh", "plan_summary"):
        assert field in response, f"missing top-level field {field!r}"
    assert response["scenario_id"] == PAYLOAD["scenario_id"], "scenario_id not echoed"
    assert isinstance(response["plan_summary"], str) and response["plan_summary"].strip()


def test_hourly_plan_shape(response):
    """PS 11.3 - exactly 24 unique hours 0..23, non-negative finite values."""
    plan = response["hourly_plan"]
    assert len(plan) == 24, f"expected 24 rows, got {len(plan)}"
    assert sorted(p["hour"] for p in plan) == list(range(24))
    for p in plan:
        for f in ("hour", "grid_kwh", "solar_used_kwh",
                  "battery_action", "battery_kwh", "battery_energy_after_kwh"):
            assert f in p, f"hour {p.get('hour')} missing {f!r}"
        assert p["battery_action"] in ("charge", "discharge", "idle")
        assert p["grid_kwh"] >= -TOL and p["solar_used_kwh"] >= -TOL and p["battery_kwh"] >= -TOL
        if p["battery_action"] == "idle":
            assert abs(p["battery_kwh"]) <= TOL, f"hour {p['hour']}: idle with battery_kwh"


# ------------------------------------------------------- interpretation
def test_interpretation_matches_ground_truth(response):
    """PS 11.1 - correct relevance, type, hours and numeric values."""
    got = response["directive_interpretation"]
    assert len(got) == len(PAYLOAD["operator_notes"]), "one entry per note required"
    assert [e["note_index"] for e in got] == list(range(len(got))), "must be in note_index order"

    by_idx = {e["note_index"]: e for e in got}
    for want in EXPECT["directives"]:
        e = by_idx[want["note_index"]]
        assert e["directive_type"] == want["directive_type"], (
            f"note {want['note_index']}: expected {want['directive_type']}, got {e['directive_type']}"
        )
        assert e["applies"] is want["applies"]

        wa = want["structured_adjustment"]
        if wa is None:
            assert e["structured_adjustment"] is None, "no_op must carry a null adjustment"
            continue
        ga = e["structured_adjustment"]
        assert ga is not None, "non-no_op needs a structured_adjustment"
        assert ga["hours"] == wa["hours"], (
            f"note {want['note_index']}: hours {ga['hours']} != {wa['hours']}"
        )
        for k in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
            if k in wa:
                assert abs(ga[k] - wa[k]) <= TOL, f"{k}: {ga.get(k)} != {wa[k]}"


def test_applies_semantics(response):
    """PS 5.1 - no_op is the only directive allowed with applies=false."""
    for e in response["directive_interpretation"]:
        if e["directive_type"] == "no_op":
            assert e["applies"] is False and e["structured_adjustment"] is None
        else:
            assert e["applies"] is True
            assert isinstance(e["structured_adjustment"], dict)


def test_hours_unique_and_ascending(response):
    """PS 5.1 / 08 - hours unique integers 0..23 in ascending order."""
    for e in response["directive_interpretation"]:
        a = e["structured_adjustment"]
        if not a or "hours" not in a:
            continue
        hrs = a["hours"]
        assert all(isinstance(h, int) and not isinstance(h, bool) for h in hrs)
        assert all(0 <= h <= 23 for h in hrs)
        assert hrs == sorted(set(hrs)), f"hours not unique+ascending: {hrs}"


# -------------------------------------------------- physics replay (judge)
def test_schedule_replays_valid(response):
    """PS 9.x / 11.3 - replay hour by hour against ground-truth directives."""
    hrs = {h["hour"]: h for h in PAYLOAD["hours"]}
    b = PAYLOAD["battery"]

    eff = {h: hrs[h]["solar_kwh"] for h in range(24)}
    for h, v in EXPECT["effective_solar_overrides"].items():
        eff[int(h)] = v

    E = b["initial_energy_kwh"]
    errors = []
    for p in sorted(response["hourly_plan"], key=lambda x: x["hour"]):
        h, g, s = p["hour"], p["grid_kwh"], p["solar_used_kwh"]
        act, k = p["battery_action"], p["battery_kwh"]
        chg = k if act == "charge" else 0.0
        dis = k if act == "discharge" else 0.0

        if s > eff[h] + TOL:
            errors.append(f"h{h}: solar_used {s} > effective solar {eff[h]}")

        lhs = g + s + dis
        rhs = hrs[h]["demand_kwh"] + chg
        if abs(lhs - rhs) > TOL:
            errors.append(f"h{h}: energy balance {lhs:.3f} != {rhs:.3f}")

        E += chg - dis
        if abs(E - p["battery_energy_after_kwh"]) > TOL:
            errors.append(f"h{h}: battery_energy_after {p['battery_energy_after_kwh']} != {E:.3f}")
        if E < b["minimum_energy_kwh"] - TOL or E > b["capacity_kwh"] + TOL:
            errors.append(f"h{h}: battery {E:.2f} outside "
                          f"[{b['minimum_energy_kwh']}, {b['capacity_kwh']}]")
        if chg > b["max_charge_kwh_per_hour"] + TOL:
            errors.append(f"h{h}: charge {chg} over rate limit")
        if dis > b["max_discharge_kwh_per_hour"] + TOL:
            errors.append(f"h{h}: discharge {dis} over rate limit")

    if abs(E - b["initial_energy_kwh"]) > TOL:
        errors.append(f"end-of-day battery {E:.3f} != initial {b['initial_energy_kwh']}")

    assert not errors, "schedule invalid:\n  " + "\n  ".join(errors)


def test_reported_totals_match_plan(response):
    """PS 11.3 - totals must match values recalculated from hourly_plan."""
    hrs = {h["hour"]: h for h in PAYLOAD["hours"]}
    plan = response["hourly_plan"]

    grid = sum(p["grid_kwh"] for p in plan)
    cost = sum(p["grid_kwh"] * hrs[p["hour"]]["tariff_bdt_per_kwh"] for p in plan)
    peak = max(p["grid_kwh"] for p in plan)

    assert abs(response["total_grid_kwh"] - grid) <= TOL, \
        f"total_grid_kwh {response['total_grid_kwh']} != recalculated {grid}"
    assert abs(response["total_cost_bdt"] - cost) <= TOL, \
        f"total_cost_bdt {response['total_cost_bdt']} != recalculated {cost}"
    assert abs(response["peak_grid_kwh"] - peak) <= TOL, \
        f"peak_grid_kwh {response['peak_grid_kwh']} != recalculated {peak}"


def test_cost_quality(response):
    """PG 08 - quality_ratio = min(1, optimal / ours). Want 1.0."""
    optimal = EXPECT["optimal_cost_bdt"]
    ours = response["total_cost_bdt"]
    ratio = min(1.0, optimal / ours) if ours > TOL else 1.0
    print(f"\n  optimal={optimal}  ours={ours}  quality_ratio={ratio:.4f}"
          f"  -> {ratio * 10:.2f}/10 optimization points")
    assert ours <= optimal + TOL, (
        f"cost {ours} exceeds known optimal {optimal} "
        f"(quality_ratio {ratio:.4f}, losing {10 * (1 - ratio):.2f} points)"
    )


# ------------------------------------------------------------ robustness
def test_latency_under_p95_target():
    """PG 08 - p95 <= 5s earns 3/3 latency points."""
    lat = []
    for _ in range(5):
        status, _, dt = _post("/optimize-energy", PAYLOAD)
        assert status == 200
        lat.append(dt)
    lat.sort()
    p95 = lat[-1]
    print(f"\n  latencies: {[f'{x:.2f}s' for x in lat]}  p95~{p95:.2f}s")
    assert p95 < TIMEOUT, f"p95 {p95:.2f}s exceeds the {TIMEOUT}s hard timeout"
    if p95 > P95_TARGET:
        pytest.fail(f"p95 {p95:.2f}s over the {P95_TARGET}s target - costs latency points")


def test_malformed_json_returns_400():
    """PS 6.1 - malformed JSON must return 400, never 500, never a crash."""
    code, _ = _post_raw("/optimize-energy", b'{"scenario_id": "X", broken')
    assert code == 400, f"expected 400 for malformed JSON, got {code}"


def test_missing_fields_rejected_not_500():
    """PS 6.1 - structurally invalid request is a client error, not a server error."""
    code, _, _ = _post("/optimize-energy", {"scenario_id": "X"})
    assert code in (400, 422), f"expected 400/422, got {code}"


def test_wrong_hour_count_rejected():
    """PS 07 - hours array must contain exactly 24 entries."""
    bad = json.loads(json.dumps(PAYLOAD))
    bad["hours"].pop()
    code, _, _ = _post("/optimize-energy", bad)
    assert code in (400, 422), f"23 hours should be rejected, got {code}"


def test_service_survives_bad_input():
    """PG 08 - bad input must not take the service down."""
    _post_raw("/optimize-energy", b"not json at all")
    _post("/optimize-energy", {"scenario_id": "X"})
    with urllib.request.urlopen(f"{BASE}/health", timeout=TIMEOUT) as r:
        assert json.loads(r.read()).get("status") == "ok", "service unhealthy after bad input"


def test_no_secret_leakage_in_errors():
    """PG 08 / NFR-06 - no key material or stack traces in error responses."""
    code, body = _post_raw("/optimize-energy", b'{"bad": ')
    text = (body.decode(errors="replace") if isinstance(body, bytes) else str(body)).lower()
    for marker in ("aiza", "api_key", "apikey", "traceback", "file \"/", "gemini_api"):
        assert marker not in text, f"error response leaked {marker!r}"


def test_repeated_requests_are_stable(response):
    """PG 08 - service must stay stable and self-consistent across repeats."""
    for i in range(3):
        status, body, _ = _post("/optimize-energy", PAYLOAD)
        assert status == 200, f"repeat {i} returned {status}"
        assert body["scenario_id"] == PAYLOAD["scenario_id"]
        assert len(body["hourly_plan"]) == 24
