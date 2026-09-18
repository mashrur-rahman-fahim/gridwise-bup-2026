# Context — GridWise Hackathon, Test/QA Role

Handoff note for a fresh Claude Code session. Everything needed is in this file;
no prior conversation required.

---

## 1. Situation

**Event:** BUP CSE Fest 2026 · Hackathon · Online Preliminary
**Round:** 4 hours, 7:00–11:00 PM (Asia/Dhaka). This doc was written at ~9:35 PM.
**Team:** two people.

- **Teammate** owns the application code (`app/`). He has his own design and is
  not following my plan. Do not restructure his work.
- **Me (Tinni)** own **testing and QA only**. Working on branch `Tinni`.

My constraint: verify correctness against the organizer's spec without touching
`app/`. Findings get reported to the teammate, not fixed by me.

---

## 2. What is being built

One deployed HTTP API with two endpoints:

| Endpoint | Behavior |
|---|---|
| `GET /health` | 200, body `{"status":"ok"}`, ready within 60s of start |
| `POST /optimize-energy` | interpretation + 24-hour plan, must return within 30s |

Required pipeline: **operator notes → LLM interprets → deterministic guardrails
validate → optimizer schedules → final replay check.**

Using an LLM only for `plan_summary` or docs fails the mandatory requirement.
Pure keyword/regex matching as the sole interpreter is non-compliant and
disqualifies the team from the shortlist.

---

## 3. Repo layout (teammate's)

```
gridwise-bup-2026/
├── .github/               CI
├── app/                   application code  — DO NOT TOUCH
├── samples/               sample case data
├── tests/
│   ├── conftest.py
│   ├── test_corner_cases.py
│   ├── test_fuzz.py
│   ├── test_guardrail.py
│   ├── test_numeric.py
│   ├── test_public_cases.py
│   └── test_request_validation.py
├── Dockerfile
├── .dockerignore
├── .env.example
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── PRD.md
├── TRD.md
└── README.md
```

He already has Dockerfile, README, CI, and a real pytest suite. Those rubric
items are covered — do not rebuild them.

---

## 4. IMMEDIATE NEXT ACTION

Before writing any new test, open `tests/test_public_cases.py` and
`tests/conftest.py` and answer two questions:

**Q1 — Does the replay use the organizer's ground truth, or the service's own
output?**

```python
# CORRECT — organizer ground truth
case["expected_output"]["directive_interpretation"]

# WRONG — the service grading its own homework
response["directive_interpretation"]
```

If it is the second, the suite has a blind spot exactly where the judge is
strictest: when the LLM misreads a note, the test passes but the judge replays
with the true directive and marks the case invalid. **This would be the single
most valuable finding of the round** — report it before writing anything new.

**Q2 — Does the suite use FastAPI `TestClient` (in-process) or a live URL?**

A `TestClient` suite never touches the real deployment. It cannot catch:

- broken deploy, cold start over 60s
- env vars missing in production, LLM call failing there
- binding to `127.0.0.1` instead of `0.0.0.0` (dies in Docker)
- real network latency and p95
- concurrency
- API keys or tracebacks leaking into responses
- whether the Docker image actually pulls and runs

His tests verify the **code**. The gap is the **deployment**. The judge only
ever sees the deployment.

Fill only the gap. Name new work distinctly, e.g. `tests/test_deployed_service.py`.

---

## 5. Test kit already written and verified

Four standalone scripts (no external deps beyond `requests`). All were run and
confirmed working against a live mock service.

| File | Purpose | Needs a URL? |
|---|---|---|
| `validate.py` | Replays plans against organizer ground truth; scores the three rubric buckets | yes (or `--self-test`) |
| `negative_test.py` | Injects 19 known bugs into reference plans, asserts each is caught | no |
| `smoke_test.py` | Contract + reliability: bad input, concurrency, latency, secret-leak scan | yes |
| `mock_service.py` | stdlib grid-only stub, lets the suite run before the real service exists | n/a |

```bash
pip install requests
python3 validate.py --self-test       # 10/10, proves no false failures
python3 negative_test.py              # 19/19, proves it catches real bugs
python3 validate.py  --url <URL>
python3 smoke_test.py --url <URL>
```

Verified results:

```
self-test        10/10 cases, 18/18 notes exact
bug-injection    19/19 caught
smoke (mock)     25/25 checks
```

`validate.py` separates errors into two buckets, because the rubric scores them
separately:

- `P` = plan/constraint error → kills the case, zero optimization credit
- `I` = interpretation error → costs interpretation points only

A case can have a valid plan and a wrong reading of the note. Reporting those as
one number hides which 25 points are being lost.

---

## 6. Scoring (100 points, automated)

| Category | Pts |
|---|---|
| LLM Directive Interpretation | 25 |
| Directive Application & Constraint Correctness | 25 |
| Optimization Quality | 10 |
| API Contract & Schema | 10 |
| Performance & Reliability | 10 |
| Deployment & Docker Fallback | 10 |
| Documentation & Local Reproducibility | 10 |

- Optimization score = `10 × avg( min(1, organizer_optimal / our_cost) )`
- **An invalid case earns 0 optimization credit regardless of how cheap it is.**
- Latency: p95 ≤5s → 3/3; 5–15s → 2/3; 15–30s → 1/3; >30s → 0 plus failures
- Video: 0 base points, tie-break only, ≤3:00

**Validity first, cost second.**

---

## 7. Domain rules the tests must enforce

### The six directive types

| `directive_type` | `structured_adjustment` |
|---|---|
| `solar_reduction` | `{hours, factor}` |
| `minimum_battery_reserve` | `{hours, minimum_energy_kwh}` |
| `no_charge_window` | `{hours}` |
| `no_discharge_window` | `{hours}` |
| `max_grid_window` | `{hours, max_grid_kwh}` |
| `no_op` | `null` |

### Interpretation rules

- Exactly one entry per note, in `note_index` order `0..N-1`. None missing, none duplicated.
- `applies = true` for every non-`no_op`.
- `applies = false` **only** for `no_op`, and then `structured_adjustment` must be `null`.
- Hours: unique integers 0–23, ascending.
- **Time windows are start-inclusive, end-exclusive.** "1 PM to 3 PM" → `[13,14]`.
  "6 PM until 10 PM" → `[18,19,20,21]`.
- **`factor` is the fraction REMAINING, not removed.** "80% reduction" → `0.2`.
  "drops to 25%" → `0.25`.
- Relative amounts convert to absolute: "50% of capacity" on a 200 kWh battery
  → `minimum_energy_kwh: 100`.
- Guardrails: `factor ∈ [0,1]`, reserve ≤ capacity, `max_grid_kwh ≥ 0`. Never
  invent a directive type; never alter demand, tariff, or battery parameters.

### Energy rules replayed by the judge

- `grid + solar_used + discharge = demand + charge`, every hour
- `0 ≤ solar_used ≤ effective_solar` (after the reduction factor is applied)
- `min_energy ≤ battery_after ≤ capacity`; hourly charge/discharge caps respected
- `battery_kwh = 0` whenever the action is `idle`
- **End of hour 23: `battery_energy_after_kwh` must equal `initial_energy_kwh`** (neutrality)
- `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh` must match values
  recalculated from `hourly_plan`
- Tolerance: 0.01 kWh / 0.01 BDT

### The bugs most likely to appear in the teammate's code

1. **Inclusive end hour** — `[13,14,15]` instead of `[13,14]`. Silent; damages
   interpretation and application at once.
2. **Inverted factor** — `0.8` for "80% reduction". Loses the numeric points and
   makes the plan over-use solar, invalidating the case.
3. **Totals taken from the LP objective** instead of recomputed from the emitted
   plan. Mismatch guaranteed.
4. **Battery not landing exactly on `initial` at hour 23.** Float drift; must be snapped.
5. **Hard-coded phrase matching** — hidden notes paraphrase the public ones, so
   `if "cleaning" in note` scores zero there.

Also: the judge replays with the **organizer's** ground-truth directive, not the
one we reported. A wrong interpretation still gets the schedule checked against
the true rule.

---

## 8. Working rules

- Branch `Tinni`. Never commit to `main` directly.
- **Do not modify `app/`.** Report findings; the teammate fixes them.
- **Never commit `.env` or any API key.** `.env.example` exists, so real keys are
  local. Check `git status` before every commit.
- Use the existing sample-case JSON in `samples/`; do not add a second copy.
- Follow the existing pytest conventions in `pytest.ini` and `conftest.py`.
- Read `TRD.md` to confirm the endpoint paths and response shape match the spec.
  **If the endpoints are not exactly `/health` and `/optimize-energy`, that is a
  disqualifying bug in his code — do not "fix" the test to match.**

---

## 9. Reporting findings

A finding is only worth something as a diagnosis. Not:

> "4 of 10 cases fail."

But:

> "SAMPLE-01, hour 12 uses 180 kWh of solar; ground truth allows 45. The factor
> is inverted — 0.75 instead of 0.25. This one bug invalidates 3 cases and zeroes
> their optimization credit."

---

## 10. Open items

- [ ] Read `tests/test_public_cases.py` + `conftest.py` → answer Q1 and Q2 in §4
- [ ] Get the deployed URL from the teammate (ask early, even if half-broken)
- [ ] Run `validate.py --url` and `smoke_test.py --url` against it
- [ ] Add only the missing deployment-facing tests
- [ ] Verify the Docker image: `docker pull` → `docker run` → `/health` on a clean machine
- [ ] Grep the repo for leaked keys before the repo goes public