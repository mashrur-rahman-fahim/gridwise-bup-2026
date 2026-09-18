#!/usr/bin/env bash
# Quick live smoke test against a running GridWise service.
#   ./scripts/live_test.sh                                  # localhost:8000
#   ./scripts/live_test.sh https://gridwise.mashrurrahman.com
set -uo pipefail

BASE="${1:-http://localhost:8000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD="$DIR/tests/payloads/live_scenario_01.json"

echo "target: $BASE"
echo

echo "== GET /health =="
code=$(curl -s -o /tmp/gw_health.$$ -w '%{http_code}' --max-time 30 "$BASE/health")
cat /tmp/gw_health.$$; echo
if [ "$code" = "200" ] && grep -q '"ok"' /tmp/gw_health.$$; then
  echo "  PASS ($code)"
else
  echo "  FAIL ($code)"; rm -f /tmp/gw_health.$$; exit 1
fi
rm -f /tmp/gw_health.$$
echo

echo "== POST /optimize-energy =="
start=$(date +%s.%N)
code=$(curl -s -o /tmp/gw_resp.$$ -w '%{http_code}' --max-time 30 \
        -X POST "$BASE/optimize-energy" \
        -H 'Content-Type: application/json' \
        --data @"$PAYLOAD")
end=$(date +%s.%N)
echo "  status : $code"
echo "  elapsed: $(echo "$end - $start" | bc)s   (target <= 5s, hard limit 30s)"
echo

if [ "$code" != "200" ]; then
  echo "FAIL - body:"; head -c 600 /tmp/gw_resp.$$; echo; rm -f /tmp/gw_resp.$$; exit 1
fi

python3 - "$PAYLOAD" /tmp/gw_resp.$$ <<'PYEOF'
import json, sys
payload = json.load(open(sys.argv[1]))
r = json.load(open(sys.argv[2]))
TOL = 0.01
OPTIMAL = 37960.0

print("interpretation:")
for e in r.get("directive_interpretation", []):
    print(f"  [{e['note_index']}] applies={str(e['applies']):<5} {e['directive_type']:<24}"
          f" {json.dumps(e['structured_adjustment'])}")

print(f"\ntotals: grid={r.get('total_grid_kwh')}  cost={r.get('total_cost_bdt')}"
      f"  peak={r.get('peak_grid_kwh')}")
print(f"summary: {str(r.get('plan_summary'))[:100]}")

hrs = {h["hour"]: h for h in payload["hours"]}
plan = r.get("hourly_plan", [])
issues = []
if len(plan) != 24 or sorted(p["hour"] for p in plan) != list(range(24)):
    issues.append("hourly_plan is not exactly hours 0-23")
else:
    grid = sum(p["grid_kwh"] for p in plan)
    cost = sum(p["grid_kwh"] * hrs[p["hour"]]["tariff_bdt_per_kwh"] for p in plan)
    peak = max(p["grid_kwh"] for p in plan)
    if abs(r["total_grid_kwh"] - grid) > TOL: issues.append(f"total_grid_kwh != recalculated {grid}")
    if abs(r["total_cost_bdt"] - cost) > TOL: issues.append(f"total_cost_bdt != recalculated {cost}")
    if abs(r["peak_grid_kwh"] - peak) > TOL: issues.append(f"peak_grid_kwh != recalculated {peak}")

    b = payload["battery"]
    eff = {h: hrs[h]["solar_kwh"] for h in range(24)}
    eff[13], eff[14] = 34.0, 28.0          # ground truth: factor 0.2 on hours 13,14
    E = b["initial_energy_kwh"]
    for p in sorted(plan, key=lambda x: x["hour"]):
        h = p["hour"]
        chg = p["battery_kwh"] if p["battery_action"] == "charge" else 0
        dis = p["battery_kwh"] if p["battery_action"] == "discharge" else 0
        if p["solar_used_kwh"] > eff[h] + TOL:
            issues.append(f"h{h} solar {p['solar_used_kwh']} > effective {eff[h]}")
        if abs(p["grid_kwh"] + p["solar_used_kwh"] + dis
               - (hrs[h]["demand_kwh"] + chg)) > TOL:
            issues.append(f"h{h} energy balance broken")
        E += chg - dis
        if E < b["minimum_energy_kwh"] - TOL or E > b["capacity_kwh"] + TOL:
            issues.append(f"h{h} battery {E:.2f} out of bounds")
    if abs(E - b["initial_energy_kwh"]) > TOL:
        issues.append(f"end battery {E:.2f} != initial {b['initial_energy_kwh']}")

cost = r.get("total_cost_bdt", 0) or 0
ratio = min(1.0, OPTIMAL / cost) if cost > TOL else 1.0
print(f"\ncost quality: ours={cost}  known optimal={OPTIMAL}"
      f"  ratio={ratio:.4f}  -> {ratio*10:.2f}/10")

print()
if issues:
    print("INVALID:")
    for i in issues: print("  -", i)
    sys.exit(1)
print("VALID - replays cleanly against ground-truth directives")
PYEOF
rc=$?
rm -f /tmp/gw_resp.$$
exit $rc
