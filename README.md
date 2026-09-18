# GridWise — LLM-Assisted Operator Directive Interpretation

Smart Campus Energy Optimization Challenge · BUP CSE Fest 2026 · Online Preliminary

A single HTTP service that reads free-text campus operator notes with a language
model, converts them into strictly validated structured directives, and produces a
provably cost-optimal 24-hour electricity schedule that obeys them.

**Live service:** <https://gridwise.mashrurrahman.com>

| | |
|---|---|
| Dashboard | <https://gridwise.mashrurrahman.com/> — browser console for trying it by hand |
| Health | <https://gridwise.mashrurrahman.com/health> |
| Optimize | `POST https://gridwise.mashrurrahman.com/optimize-energy` |

```bash
curl -s https://gridwise.mashrurrahman.com/health      # -> {"status":"ok"}
```

Measured against the ten public sample cases on the live endpoint: every operator
note interpreted exactly, total cost equal to the organizer optimal on all ten, all
ten valid under an independent replay against ground-truth directives, p95 latency
2.5 s against a 5 s budget.

---

## Contents

- [What this does](#what-this-does)
- [Architecture](#architecture)
- [Try the live service](#try-the-live-service)
- [Quickstart from a clean machine](#quickstart-from-a-clean-machine)
- [Docker (fallback execution path)](#docker-fallback-execution-path)
- [Configuration](#configuration)
- [API](#api)
- [Testing](#testing)
- [How the pieces work](#how-the-pieces-work)
- [Dependencies and credits](#dependencies-and-credits)
- [Known limitations](#known-limitations)
- [Secret handling](#secret-handling)

---

## What this does

A campus draws power from the grid (hourly tariff), rooftop solar (free, daylight
only), and a battery (stores energy, generates none). The next 24 hours of demand,
solar and tariff arrive in the request.

Operators also send 1–3 short notes in plain English. Some change the schedule:

> "Facilities will wash the rooftop solar panels from noon until 2 PM. During
> cleaning, usable solar should be treated as roughly 25% of the forecast."

Others are distractors and must be ignored:

> "The sports office moved next month's registration deadline."

The service interprets each note, validates the interpretation deterministically,
applies it to the optimization model, and returns both the interpretation and the
resulting schedule.

---

## Architecture

```
 judge harness
      │ POST /optimize-energy
      ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 1. HTTP layer      FastAPI + Pydantic                    │
 │    exact request schema; malformed input -> 400          │
 ├──────────────────────────────────────────────────────────┤
 │ 2. Interpreter     Gemini (gemini-3.1-flash-lite)        │
 │    notes -> directive JSON. temperature 0.               │
 │    Receives ONLY the notes + battery capacity/minimum.   │
 ├──────────────────────────────────────────────────────────┤
 │ 3. Parse + repair  deterministic                         │
 │    strips fences/prose; coerces only unambiguous slips   │
 ├──────────────────────────────────────────────────────────┤
 │ 4. Guardrail       deterministic, treats model output    │
 │    as untrusted. 11 checks. Fail -> retry -> no_op.      │
 ├──────────────────────────────────────────────────────────┤
 │ 5. Apply           directives become variable bounds     │
 ├──────────────────────────────────────────────────────────┤
 │ 6. Optimize        PuLP -> CBC linear program            │
 │    120 variables, 49 constraints, ~10 ms median          │
 ├──────────────────────────────────────────────────────────┤
 │ 7. Post-process    net battery, round, sum rounded rows  │
 ├──────────────────────────────────────────────────────────┤
 │ 8. Self-check      replay our own answer independently   │
 └──────────────────────────────────────────────────────────┘
      │ 200 + JSON
      ▼
```

**The language model is inside the constraint-producing path, not decorating the
output.** Removing it leaves the optimizer with no directives at all. There is no
phrase matching against note text anywhere in the codebase.

---

## Try the live service

No setup required. These run against the deployed instance:

```bash
curl -s https://gridwise.mashrurrahman.com/health
# -> {"status":"ok"}
```

```bash
curl -s -X POST https://gridwise.mashrurrahman.com/optimize-energy \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON' | python3 -m json.tool
{
  "scenario_id": "GRID-DEMO",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {"hour":0,"demand_kwh":90,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":1,"demand_kwh":85,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":2,"demand_kwh":80,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":3,"demand_kwh":80,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":4,"demand_kwh":85,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":5,"demand_kwh":95,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":6,"demand_kwh":110,"solar_kwh":5,"tariff_bdt_per_kwh":8},
    {"hour":7,"demand_kwh":130,"solar_kwh":20,"tariff_bdt_per_kwh":10},
    {"hour":8,"demand_kwh":150,"solar_kwh":50,"tariff_bdt_per_kwh":12},
    {"hour":9,"demand_kwh":165,"solar_kwh":90,"tariff_bdt_per_kwh":14},
    {"hour":10,"demand_kwh":175,"solar_kwh":130,"tariff_bdt_per_kwh":16},
    {"hour":11,"demand_kwh":180,"solar_kwh":160,"tariff_bdt_per_kwh":16},
    {"hour":12,"demand_kwh":185,"solar_kwh":180,"tariff_bdt_per_kwh":15},
    {"hour":13,"demand_kwh":180,"solar_kwh":170,"tariff_bdt_per_kwh":14},
    {"hour":14,"demand_kwh":170,"solar_kwh":140,"tariff_bdt_per_kwh":13},
    {"hour":15,"demand_kwh":165,"solar_kwh":90,"tariff_bdt_per_kwh":14},
    {"hour":16,"demand_kwh":170,"solar_kwh":45,"tariff_bdt_per_kwh":18},
    {"hour":17,"demand_kwh":185,"solar_kwh":10,"tariff_bdt_per_kwh":22},
    {"hour":18,"demand_kwh":205,"solar_kwh":0,"tariff_bdt_per_kwh":28},
    {"hour":19,"demand_kwh":215,"solar_kwh":0,"tariff_bdt_per_kwh":30},
    {"hour":20,"demand_kwh":205,"solar_kwh":0,"tariff_bdt_per_kwh":26},
    {"hour":21,"demand_kwh":175,"solar_kwh":0,"tariff_bdt_per_kwh":18},
    {"hour":22,"demand_kwh":135,"solar_kwh":0,"tariff_bdt_per_kwh":10},
    {"hour":23,"demand_kwh":105,"solar_kwh":0,"tariff_bdt_per_kwh":7}
  ],
  "battery": {
    "capacity_kwh":220,"initial_energy_kwh":110,"minimum_energy_kwh":40,
    "max_charge_kwh_per_hour":50,"max_discharge_kwh_per_hour":50
  }
}
JSON
```

Expected: `solar_reduction` on hours `[13, 14]` with `factor 0.2`, the cafeteria note as
`no_op`, a 24-row `hourly_plan`, and `total_cost_bdt` of `37960.0`.

> `/optimize-energy` is **POST only**. Opening it in a browser sends a GET and
> correctly returns `405 Method Not Allowed`. Only `/health` is viewable in a browser.

---

## Quickstart from a clean machine

Requires Python 3.11+ and network access to the Gemini API.

```bash
git clone https://github.com/mashrur-rahman-fahim/gridwise-bup-2026.git
cd gridwise-bup-2026

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here    # name documented; value never committed

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The commands below target your **local** instance, so leave the server above
running and open a second terminal:

```bash
# 1. readiness
curl -s http://localhost:8000/health
# -> {"status":"ok"}

# 2. one public sample case end to end
python - <<'PY'
import json, urllib.request
case = json.load(open("samples/public_sample_cases.json"))["cases"][0]["input"]
req = urllib.request.Request("http://localhost:8000/optimize-energy",
    data=json.dumps(case).encode(), headers={"Content-Type": "application/json"})
out = json.load(urllib.request.urlopen(req, timeout=60))
print("scenario:", out["scenario_id"])
print("cost    :", out["total_cost_bdt"], "BDT   (organizer optimal: 38365)")
print("hours   :", len(out["hourly_plan"]))
for d in out["directive_interpretation"]:
    print(f"  note {d['note_index']}: {d['directive_type']} {d['structured_adjustment']}")
PY
```

**Expected result** for `SAMPLE-01`:

```
scenario: SAMPLE-01
cost    : 38365.0 BDT   (organizer optimal: 38365)
hours   : 24
  note 0: solar_reduction {'hours': [12, 13], 'factor': 0.25}
  note 1: no_op None
```

Or with curl directly:

```bash
curl -s -X POST http://localhost:8000/optimize-energy \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON' | python3 -m json.tool | head -30
{
  "scenario_id": "GRID-DEMO",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {"hour":0,"demand_kwh":90,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":1,"demand_kwh":85,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":2,"demand_kwh":80,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":3,"demand_kwh":80,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":4,"demand_kwh":85,"solar_kwh":0,"tariff_bdt_per_kwh":5},
    {"hour":5,"demand_kwh":95,"solar_kwh":0,"tariff_bdt_per_kwh":6},
    {"hour":6,"demand_kwh":110,"solar_kwh":5,"tariff_bdt_per_kwh":8},
    {"hour":7,"demand_kwh":130,"solar_kwh":20,"tariff_bdt_per_kwh":10},
    {"hour":8,"demand_kwh":150,"solar_kwh":50,"tariff_bdt_per_kwh":12},
    {"hour":9,"demand_kwh":165,"solar_kwh":90,"tariff_bdt_per_kwh":14},
    {"hour":10,"demand_kwh":175,"solar_kwh":130,"tariff_bdt_per_kwh":16},
    {"hour":11,"demand_kwh":180,"solar_kwh":160,"tariff_bdt_per_kwh":16},
    {"hour":12,"demand_kwh":185,"solar_kwh":180,"tariff_bdt_per_kwh":15},
    {"hour":13,"demand_kwh":180,"solar_kwh":170,"tariff_bdt_per_kwh":14},
    {"hour":14,"demand_kwh":170,"solar_kwh":140,"tariff_bdt_per_kwh":13},
    {"hour":15,"demand_kwh":165,"solar_kwh":90,"tariff_bdt_per_kwh":14},
    {"hour":16,"demand_kwh":170,"solar_kwh":45,"tariff_bdt_per_kwh":18},
    {"hour":17,"demand_kwh":185,"solar_kwh":10,"tariff_bdt_per_kwh":22},
    {"hour":18,"demand_kwh":205,"solar_kwh":0,"tariff_bdt_per_kwh":28},
    {"hour":19,"demand_kwh":215,"solar_kwh":0,"tariff_bdt_per_kwh":30},
    {"hour":20,"demand_kwh":205,"solar_kwh":0,"tariff_bdt_per_kwh":26},
    {"hour":21,"demand_kwh":175,"solar_kwh":0,"tariff_bdt_per_kwh":18},
    {"hour":22,"demand_kwh":135,"solar_kwh":0,"tariff_bdt_per_kwh":10},
    {"hour":23,"demand_kwh":105,"solar_kwh":0,"tariff_bdt_per_kwh":7}
  ],
  "battery": {
    "capacity_kwh":220,"initial_energy_kwh":110,"minimum_energy_kwh":40,
    "max_charge_kwh_per_hour":50,"max_discharge_kwh_per_hour":50
  }
}
JSON
```

---

## Docker (fallback execution path)

Exact pullable reference:

```
ghcr.io/mashrur-rahman-fahim/gridwise-bup-2026:v1
```

`:v1` is re-pushed by CI on every merge to `main`, so it always matches the code in
this repository. For an immutable reference, each build is also tagged with its
commit, and the current one is:

```
ghcr.io/mashrur-rahman-fahim/gridwise-bup-2026:53943d3cb54481d07b6c6ff1a5413778883ed2f4
ghcr.io/mashrur-rahman-fahim/gridwise-bup-2026@sha256:d5fcab80b8bcf7efdc429fecac6f864d2a1eec7a47c34f803f520d1a2bae63c6
```

That digest moves whenever `main` moves; `:v1` does not need updating.

```bash
docker pull ghcr.io/mashrur-rahman-fahim/gridwise-bup-2026:v1

docker run -d --name gridwise -p 8000:8000 \
  -e GEMINI_API_KEY=your_key_here \
  ghcr.io/mashrur-rahman-fahim/gridwise-bup-2026:v1

curl -s http://localhost:8000/health      # -> {"status":"ok"}
```

The image binds `0.0.0.0`, exposes port `8000`, and contains **no credentials**.
The key is supplied only at run time.

To build locally instead:

```bash
docker build -t gridwise:local .
docker run -d -p 8000:8000 -e GEMINI_API_KEY=your_key_here gridwise:local
```

---

## Configuration

All configuration is environment-based. **Names are documented here; values are
never committed.** See `.env.example`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | yes | — | Credential for operator-note interpretation |
| `GEMINI_MODEL` | no | `gemini-3.1-flash-lite` | Primary interpreter model |
| `GEMINI_FALLBACK_MODEL` | no | `gemini-2.5-flash` | Used if the primary errors |
| `PORT` | no | `8000` | Bind port |
| `LLM_TIMEOUT_S` | no | `9` | Per-call ceiling for one model request |

**Model and provider:** Google Gemini, model id `gemini-3.1-flash-lite`, called over
the public `generativelanguage.googleapis.com` REST API.

Without `GEMINI_API_KEY` the service still starts and returns valid schedules; every
note degrades to `no_op`. This is deliberate — see
[Known limitations](#known-limitations).

---

## API

### `GET /`

A self-contained browser dashboard for exercising the service by hand: edit operator
notes, adjust the battery, run the optimizer, and read back the interpretation and the
24-hour schedule. No external requests, no build step, not part of the judged contract.

### `GET /health`

```json
{ "status": "ok" }
```

Returns 200 once the process is serving. No external dependency is touched, so it
stays cheap under repeated polling and answers well within 60 s of start.

### `POST /optimize-energy`

Request and response follow the Problem Statement exactly. Status codes:

| Code | Meaning |
|---|---|
| `200` | Valid interpretation + 24-hour schedule |
| `400` | Malformed JSON or structurally invalid request |
| `500` | Controlled internal error; generic body, never a stack trace |

#### Sample response

Public case `SAMPLE-01`, taken from the live service. `hourly_plan` carries all 24
rows; a few are shown here.

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {"note_index": 0, "applies": true, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [12, 13], "factor": 0.25}, "explanation": "Usable solar limited to 25% of forecast during hours 12-13."},
    {"note_index": 1, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "This note does not affect today's 24-hour energy schedule."}
  ],
  "hourly_plan": [
    {"hour": 0, "grid_kwh": 40.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 50.0, "battery_energy_after_kwh": 60.0},
    {"hour": 3, "grid_kwh": 130.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 50.0, "battery_energy_after_kwh": 140.0},
    ...
    {"hour": 12, "grid_kwh": 90.0, "solar_used_kwh": 45.0, "battery_action": "discharge", "battery_kwh": 50.0, "battery_energy_after_kwh": 70.0},
    {"hour": 19, "grid_kwh": 165.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 50.0, "battery_energy_after_kwh": 90.0},
    {"hour": 23, "grid_kwh": 155.0, "solar_used_kwh": 0.0, "battery_action": "charge", "battery_kwh": 50.0, "battery_energy_after_kwh": 110.0}
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 187.5,
  "plan_summary": "Applied operator directives: solar_reduction. Charges the battery during 9 low-tariff hours. Discharges across 10 higher-tariff hours. Battery returns to its initial level by the end of hour 23. Total grid cost 38365.00 BDT."
}
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

| Suite | What it covers |
|---|---|
| `test_public_cases.py` | All 10 public samples: exact match to organizer optimal cost, plus independent replay |
| `test_request_validation.py` | 33 request-envelope cases (wrong hour counts, non-finite values, note limits) |
| `test_guardrail.py` | 44 hostile model outputs, plus repair-rescue and hard-reject leak checks |
| `test_corner_cases.py` | 21 solver corner cases including three bug regressions |
| `test_numeric.py` | Floating-point self-consistency at extreme scales |
| `test_fuzz.py` | 400 randomised scenarios with randomised directives |

Run just the public-sample check:

```bash
pytest tests/test_public_cases.py -q      # expect: 10 passed
```

Against a running service, including the deployed one:

```bash
./scripts/live_test.sh https://gridwise.mashrurrahman.com

GRIDWISE_URL=https://gridwise.mashrurrahman.com pytest tests/test_live_endpoint.py -q
```

`tests/test_live_endpoint.py` skips unless `GRIDWISE_URL` is set, so CI is unaffected.

---

## How the pieces work

### The language model

Receives **only** the operator notes plus `capacity_kwh` and `minimum_energy_kwh`.
The 24-hour demand/solar/tariff table is deliberately withheld — what the model
cannot see, it cannot invent. It returns one directive object per note and nothing
else. It never chooses a battery action, computes a cost, or produces a schedule.

The prompt teaches the three conventions the specification defines, rather than
hoping they are inferred:

- windows are start-inclusive and **end-exclusive** — "1 PM to 3 PM" is `[13, 14]`
- `factor` is the fraction of solar that **remains** — an 80% reduction is `0.2`
- percentage reserves are a share of **battery capacity**, resolved to kWh
- charging versus discharging is decided by **energy direction**, not vocabulary:
  "pack intake", "BESS grid draw" and "mains import to the storage" all mean
  charging, however loosely an operator phrases it
- "tomorrow", "tonight" and "this evening" are **inside** the 24-hour horizon and
  still produce directives; only genuinely out-of-horizon plans ("next month",
  "once the new feeder is installed") are `no_op`

### The guardrail

Model output is treated as untrusted input. Eleven deterministic checks cover
directive type, note mapping and ordering, hour validity, `applies` semantics,
adjustment shape, and numeric ranges. A failure triggers one retry that feeds the
exact validation error back to the model; a second failure degrades those notes to
`no_op` rather than guessing.

A separate repair pass runs first and fixes only slips with exactly one sane
reading — `"0.25"` to `0.25`, `[12,12,13]` to `[12,13]`, `[13,12]` to `[12,13]`,
`"25%"` to `0.25`. Genuinely ambiguous output such as `factor: 1.5` is **not**
repaired; it is rejected so the retry can correct it.

### The optimizer

A linear program over 120 variables and 49 constraints. Each directive becomes a
variable bound, so the solver needs no per-directive branching:

| Directive | Becomes |
|---|---|
| `solar_reduction` | upper bound on solar used |
| `no_charge_window` | charge upper bound 0 |
| `no_discharge_window` | discharge upper bound 0 |
| `minimum_battery_reserve` | raised lower bound on stored energy |
| `max_grid_window` | upper bound on grid purchased |

Objective is `Σ grid[h] × tariff[h]`. Constraints are the hourly energy balance, the
battery recurrence, and end-of-day neutrality. CBC reports `Optimal` only with a
proof certificate, so a solved schedule is the cheapest legal one for those
directives — not a heuristic's best guess.

The objective prices grid energy only, with no tie-break between equally-priced
plans. When every hour carries the same tariff there is nothing to separate two
schedules of identical cost, so which one is returned — and therefore the reported
`solar_used_kwh` and `peak_grid_kwh` — depends on which optimal vertex the solver
lands on. Cost, the scored quantity, is unaffected.

Where two directives of the same type overlap on an hour, the **tighter** value
wins. Over-constraining keeps a plan valid; under-constraining does not.

### Post-processing

The solver is indifferent between charging and discharging in the same hour since
the cost is identical, but the schema demands exactly one action per hour. Collapsing
to the net is exactly cost-neutral because charge and discharge appear in the model
only as their difference. Magnitudes are rounded before the battery level is
accumulated, so the published rows reproduce the totals exactly when recomputed.

### Self-check

Before responding, the finished plan is replayed by `app/replay.py` — written
independently of the optimizer, so a shared misreading of the specification cannot
hide itself.

---

## Project layout

```
app/
  main.py            FastAPI app, both endpoints, orchestration, self-audit
  schemas.py         request and response models
  llm.py             prompt, Gemini call, retry and degradation
  repair.py          coercion of unambiguous model slips
  guardrail.py       deterministic validation of model output
  apply.py           directives to optimizer bounds, tightest wins
  optimizer.py       linear program and infeasibility fallback
  postprocess.py     battery netting, rounding, totals
  replay.py          independent schedule replay
  contract_audit.py  full response-contract audit
  web/index.html     browser dashboard
tests/               unit, corner-case, fuzz, contract and live suites
samples/             public sample cases
scripts/live_test.sh smoke test against a running service
```

---

## Dependencies and credits

| Package | Licence | Used for |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | HTTP layer |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3 | ASGI server |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Request/response validation |
| [PuLP](https://github.com/coin-or/pulp) | MIT | LP modelling |
| [COIN-OR CBC](https://github.com/coin-or/Cbc) | EPL-2.0 | LP solver (bundled with PuLP) |
| [httpx](https://github.com/encode/httpx) | BSD-3 | HTTP client for the model API |
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Test runner |

External service: **Google Gemini API** (`generativelanguage.googleapis.com`).

`PRD.md` and `TRD.md` in this repository document the requirements and the technical
design in full.

---

## Known limitations

- **Hosted model dependency.** Interpretation requires the Gemini API. If it is
  unreachable the service stays up and returns valid schedules, but every note
  degrades to `no_op`, so directive-specific constraints are not applied. This is a
  deliberate trade: a valid schedule missing one directive scores better than an
  unavailable service.
- **Infeasible directive sets.** Valid scenarios are guaranteed feasible. If an
  extraction produces a contradictory set, the service drops the smallest number of
  directives needed to recover a solution rather than failing. That returns a valid
  response, but it does not recover the affected case's directive score.
- **Unseen phrasing.** Interpretation is benchmarked against the published samples
  and a purpose-built paraphrase set covering every documented convention. Hidden
  phrasings outside that distribution remain the principal residual risk.
- **No response caching.** Hidden notes are unseen by definition, so a cache would
  never hit during evaluation.
- **Single worker, and the solver blocks it.** One uvicorn worker keeps behaviour
  deterministic. The model call is awaited and does not block, so several requests
  can have calls in flight at once, but the linear program runs inline on the event
  loop: about 10 ms median, up to ~22 ms, and ~38 ms on the rare path where an
  infeasible directive set is retried as subsets. Under heavy concurrency those
  blocking slices serialise. They are small next to the 1.5-2.5 s model call, so
  this has not been worth moving to a worker thread.

---

## Secret handling

- `GEMINI_API_KEY` is read from the environment only. It is never committed, never
  written to logs, and never included in a response body.
- `.gitignore` excludes `.env`, `*.env`, `*.key` and related files.
- The Docker image contains no credentials; the key is supplied with `-e` at run time.
- `500` responses return a generic message. Stack traces, exception text and
  configuration values are never sent to the client.
- `.env.example` documents variable **names** with empty values.
