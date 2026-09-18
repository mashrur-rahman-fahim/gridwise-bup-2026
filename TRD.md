# Technical Requirements Document (TRD)
## GridWise — LLM-Assisted Operator Directive Interpretation
### BUP CSE Fest 2026 · Hackathon · Online Preliminary Round

| Field | Value |
|---|---|
| Document | TRD v1.0 |
| Companion | `PRD.md` v1.0 (requirements) |
| Scope | Architecture, algorithms, module specs, deployment, testing |
| Authority | Every `TR-` here traces to an `FR-`/`DR-`/`GR-`/`NFR-` in the PRD |

> **Rule:** the PRD says *what*. This TRD says *how*. Where they conflict, the PRD wins; where the PRD and the Problem Statement conflict, the **Problem Statement** wins (PRD §0.1).

---

## 1. Architecture

### 1.1 Pipeline

```
   Judge harness
        │  POST /optimize-energy   (scenario JSON)
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. HTTP LAYER          FastAPI + Pydantic                     │
│    validate envelope · 400 on malformed · echo scenario_id    │
└───────────────┬───────────────────────────────────────────────┘
                │ notes[] + battery.capacity + battery.minimum
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. INTERPRETER         LLM (Gemini)                           │
│    notes -> directive JSON.  temperature=0.  JSON mime type.  │
│    NEVER sees the 24-hour table.                              │
└───────────────┬───────────────────────────────────────────────┘
                │ raw text
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. PARSE + REPAIR      deterministic                          │
│    strip fences/prose · coerce unambiguous sloppiness only    │
└───────────────┬───────────────────────────────────────────────┘
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. GUARDRAIL           deterministic, hostile-input posture   │
│    11 checks. fail -> retry once -> no_op fallback.           │
└───────────────┬───────────────────────────────────────────────┘
                │ validated directives
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 5. APPLY               directives -> variable bounds          │
│    tightest-wins on overlap                                   │
└───────────────┬───────────────────────────────────────────────┘
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 6. OPTIMIZE            PuLP -> CBC  (linear program)          │
│    120 vars · 49 constraints · ~10 ms · status must be Optimal│
│    Infeasible -> subset-drop ladder                           │
└───────────────┬───────────────────────────────────────────────┘
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 7. POST-PROCESS        net battery · round · sum rounded rows │
└───────────────┬───────────────────────────────────────────────┘
                ▼
┌───────────────────────────────────────────────────────────────┐
│ 8. SELF-CHECK          replay our own answer like the judge   │
└───────────────┬───────────────────────────────────────────────┘
                ▼  200 + response JSON
```

### 1.2 Design principle

Three components, each doing the one job it cannot fail at:

| Component | Strength | Never asked to |
|---|---|---|
| **LLM** | messy human language | do arithmetic, pick battery actions, build schedules |
| **Guardrail** | saying "no" deterministically | interpret meaning |
| **LP solver** | 24 coupled constraints, exact optimum | read English |

**Satisfies FR-07 (hard eligibility gate):** the LLM's structured output is the *only* source of the optimization constraints. Remove it and the optimizer has no directives. No regex/phrase-matching interpreter exists anywhere in the path.

---

## 2. Technology Stack

| Layer | Choice | Rationale | PRD ref |
|---|---|---|---|
| Web framework | **FastAPI** | Pydantic validation gives PRD §19.1 400-handling for free; ASGI; auto request-schema enforcement | FR, NFR-05 |
| Server | **uvicorn** | single worker (deterministic), `--host 0.0.0.0` | DEL-05 |
| Validation | **Pydantic v2** | declarative schema = §9 request contract | NFR-05 |
| LLM | **Gemini 3.1 Flash Lite** | 92/92 exact, p95 1.57 s — see §3.2 | FR-01, NFR-03 |
| LLM transport | **stdlib `urllib`** over REST | zero SDK version risk; one less dependency to break at 10 PM | NFR-04 |
| Modelling | **PuLP** | readable LP, ships CBC | FR-06 |
| Solver | **CBC** (bundled with PuLP) | returns proven `Optimal`; no license; ~10 ms | FR-06 |
| Container | **python:3.11-slim** | small, CBC binary works | DEL-05 |

**Dependency count kept minimal deliberately** — every dependency is a thing that can fail during the 4-hour window.

---

## 3. LLM Interpreter

### 3.1 Requirements

| ID | Requirement | Source |
|---|---|---|
| **TR-3.1** | LLM must produce the structured interpretation used by the optimizer | FR-07 |
| **TR-3.2** | `temperature = 0` — translator, not author | determinism |
| **TR-3.3** | `responseMimeType: application/json` — guarantees parseable output | GR-10 |
| **TR-3.4** | LLM receives **only** the notes + `capacity_kwh` + `minimum_energy_kwh` | GR-07 (no invention) |
| **TR-3.5** | Whole-request p95 ≤ 5 s ⇒ LLM budget ≈ 4.8 s | NFR-03 |
| **TR-3.6** | One retry on guardrail failure, then `no_op` fallback | GR-10, NFR-04 |

**TR-3.4 rationale:** the 24-hour demand/solar/tariff table is never sent. What the model cannot see, it cannot hallucinate. This is a guardrail, not an optimization.

### 3.2 Model selection

Benchmarked on **34 scenarios / 46 notes**: the 10 public cases plus a purpose-built paraphrase set covering every documented trap — the Problem Statement's own three equivalent phrasings, percent-of-capacity arithmetic, 24-hour clock, midnight-wrapping windows, single-hour windows, "halves"/"one-fifth"/"40% drop" factor wording, and pure distractors.

Scored per note on: directive type · exact hours array · numeric value within 0.01 · all three together (**exact**).

**Selection criteria, fixed before results were seen:**
1. **Exact accuracy first.** Interpretation + application = 50 of 100 points.
2. **p95 must leave headroom under 5 s** for the full request (NFR-03).
3. Tie → prefer lower latency; the latency band is worth 3 points, marginal accuracy is not.

#### 3.2.1 Results — 12 models, 34 scenarios, 46 notes each

Scored per note: `directive_type` · exact `hours` array · numeric value within 0.01 · **exact** = all three.

| Model | exact | p50 | p95 | max |
|---|---|---|---|---|
| **gemini-3.1-flash-lite** | **46/46** | **1.38 s** | **1.76 s** | **1.87 s** |
| gemini-2.5-flash | 46/46 | 3.01 s | 4.27 s | 5.13 s |
| gemini-3-flash-preview | 46/46 | 3.63 s | 5.14 s | 5.32 s |
| gemini-3.8-flash | 46/46 | 2.98 s | 5.29 s | 15.57 s |
| gemini-3.6-flash | 46/46 | 4.30 s | 6.04 s | 6.76 s |
| gemini-3.7-flash | 46/46 | 2.94 s | 8.15 s | 11.83 s |
| gemini-flash-latest | 46/46 | 2.71 s | 8.85 s | 10.10 s |
| gemini-3.1-pro-preview | 46/46 | 6.94 s | 10.23 s | 11.89 s |
| gemini-3.5-flash | 46/46 | 6.72 s | 10.27 s | 12.01 s |
| gemini-2.5-flash-lite | 45/46 | 1.20 s | 1.34 s | 7.88 s |
| gemini-3.5-flash-lite | 45/46 | 1.49 s | 1.83 s | 1.99 s |
| gemini-flash-lite-latest | 45/46 | 1.29 s | 1.87 s | 6.28 s |

Those latencies were gathered with six models running concurrently, which can distort timing. **Re-measured sequentially, no concurrency, 2 passes (68 calls):**

| Model | exact | mean | p50 | p90 | **p95** | p99 | max |
|---|---|---|---|---|---|---|---|
| **gemini-3.1-flash-lite** | **92/92** | 1.32 s | 1.28 s | 1.50 s | **1.57 s** | 1.68 s | 1.68 s |

#### 3.2.2 Decision

> **SELECTED: `gemini-3.1-flash-lite`**

| Criterion | Result |
|---|---|
| Accuracy | **92/92 exact** across two sequential passes — type, hours, and numeric value all correct on every note |
| p95 latency | **1.57 s** — leaves **≈3.4 s of headroom** inside the 5 s band for full 3/3 latency points (NFR-03) |
| Tail risk | max 1.68 s across 68 calls. **No tail.** Compare `gemini-3.8-flash` (max 15.57 s) — a single such spike is a scored failure |
| Timeout margin | 30 s hard limit (NFR-02) accommodates the prompt **plus one full retry** with ~27 s to spare |

**Fallback: `gemini-2.5-flash`** (46/46, p95 4.27 s) via the `GEMINI_MODEL` env var — used only if the primary is unavailable during the window (NFR-10). It still fits the 5 s band, with less margin.

**Notable:** the strongest accuracy was *not* bought with latency. Nine of twelve models scored 46/46, so this task is well within current model capability — which makes the tight, tail-free latency distribution the deciding factor rather than raw capability.

**Caveat, stated honestly:** 9/12 models scoring perfectly means this benchmark does not discriminate on accuracy. The hidden set may contain harder phrasings than the paraphrase suite. The decision therefore rests on latency and tail behaviour, where the separation is large and unambiguous.

### 3.3 Prompt design

Teaches the three documented traps explicitly rather than hoping the model infers them:

```
1. HOURS integers 0-23. Windows START-INCLUSIVE, END-EXCLUSIVE.
   "1 PM to 3 PM" -> [13,14]   "noon until 2 PM" -> [12,13]
   "05:00 to 08:00" -> [5,6,7] "at 11 PM" -> [23]
   "10 PM until 2 AM" -> [0,1,22,23]  (ascending!)
2. FACTOR = fraction of solar that REMAINS, never the fraction removed.
   "drops to 20%" -> 0.2   "80% reduction" -> 0.2   "one-fifth" -> 0.2
   "only 60 percent usable" -> 0.6   "halves" -> 0.5   "40% drop" -> 0.6
3. PERCENTAGE RESERVES are of BATTERY CAPACITY. Compute kWh yourself.
4. Notes about staffing, menus, bookings, deadlines, paperwork -> no_op.
5. applies=true for all but no_op. no_op -> applies=false + null adjustment.
6. ONE entry per note, note_index order. Never invent a directive type.
```

Maps to FR-20, FR-21, FR-22, FR-03, FR-15, FR-10/11/12.

---

## 4. Parse & Repair Layer

### 4.1 Parse (`parse_llm`)

Handles the three ways a model wraps JSON:
1. Clean JSON → `json.loads`
2. Markdown fenced (` ```json … ``` `) → strip fence
3. Prose around an array → slice from first `[` to last `]`

Nothing parseable → raise → retry path.

### 4.2 Repair (`repair`)

> **Governing rule: repair only when there is exactly one sane reading. Ambiguity is left alone and rejected, triggering a retry.**

Rejecting a recoverable note is self-harm: it loses the interpretation point *and* leaves the constraint unapplied, invalidating the whole case (PEN-02 + PEN-03).

| Repair | Example | Justification |
|---|---|---|
| Numeric strings → numbers | `"0.25"` → `0.25` | one reading |
| Percent strings → fraction | `"25%"` → `0.25` | one reading |
| Integral floats → int | `12.0` → `12` | JSON has no int/float distinction |
| Dedupe hours | `[12,12,13]` → `[12,13]` | GR-03 requires unique |
| Sort hours | `[13,12]` → `[12,13]` | GR-03 requires ascending |
| Drop extra keys | `{hours,factor,zz}` → `{hours,factor}` | shape fixed by §6.1 |
| Bool strings | `"true"` → `true` | one reading |
| Lowercase type | `"SOLAR_REDUCTION"` → `solar_reduction` | one reading |
| Missing `note_index` | infer from array position | unambiguous when length matches note count |
| `no_op` pairing | force `applies=false`, `adjustment=null` | GR-09 mandates it |
| Valid adjustment present + `applies=false` | force `applies=true` | FR-15: only `no_op` may be false |

**Explicitly NOT repaired** (ambiguous → retry): `factor: 1.5` · `factor: 25` bare · invented type · `hour: 24` · `reserve > capacity` · wrong entry count · empty `hours` · missing required key.

**Measured: 10 of 12 sloppy-but-unambiguous outputs rescued, each landing on the exact ground-truth value, with zero leakage into the hard-reject set.**

---

## 5. Guardrail Layer

Implements GR-01…GR-10. Raises on first violation.

| # | Check | Guards against | PRD |
|---|---|---|---|
| 1 | entry count == note count | missing/extra mapping | GR-02 |
| 2 | `note_index` set == `{0..N-1}`, no duplicates | FR-11 | GR-02 |
| 3 | `directive_type` ∈ six | invented type | GR-01 |
| 4 | `applies` is a real bool | type confusion | GR-09 |
| 5 | `no_op` ⇒ `applies=false` ∧ adjustment `null` | FR-14 | GR-09 |
| 6 | non-`no_op` ⇒ `applies=true` ∧ dict adjustment | FR-15 | GR-09 |
| 7 | adjustment keys == exact required set | wrong shape | GR-09 |
| 8 | hours: ints, 0–23, unique, ascending | FR-16 | GR-03 |
| 9 | `0 ≤ factor ≤ 1` and finite | GR-04 | GR-04 |
| 10 | `0 ≤ reserve ≤ capacity` and finite | GR-05 | GR-05 |
| 11 | `max_grid_kwh ≥ 0` and finite | GR-06 | GR-06 |

Output is **normalised** (sorted hours, floats coerced, `explanation` truncated to 300 chars) and sorted by `note_index` so FR-11 holds by construction.

**Why `reserve ≤ capacity` (check 10) matters operationally:** a hallucinated `500` on a 220 kWh battery makes the LP **Infeasible** — no plan at all, case lost. One `if` converts a catastrophe into a retry.

---

## 6. Directive Application

```python
eff   = {h: hours[h].solar_kwh for h in range(24)}
nochg, nodis, reserve, gridcap = set(), set(), {}, {}

for d in validated:
    if   t == "solar_reduction":
        for h in a["hours"]: eff[h] = min(eff[h], solar[h] * a["factor"])          # TIGHTEST
    elif t == "no_charge_window":        nochg |= set(a["hours"])
    elif t == "no_discharge_window":     nodis |= set(a["hours"])
    elif t == "minimum_battery_reserve":
        for h in a["hours"]: reserve[h] = max(reserve.get(h,0), a["minimum_energy_kwh"])  # TIGHTEST
    elif t == "max_grid_window":
        for h in a["hours"]: gridcap[h] = min(gridcap.get(h,inf), a["max_grid_kwh"])      # TIGHTEST
```

**TR-6.1 — tightest-wins (FR-30 / AMB-02).** Implements PS §5.3's `max(base, directive)` semantics, extended consistently to the other constraint types.

> **This was a real bug, found by fuzzing (2 failures in 400).** The original code used last-directive-wins. With two overlapping reserve notes where the second is lower, the plan targets the lower floor while the judge enforces the higher one — silently invalid. Over-constraining stays valid; under-constraining does not.

---

## 7. Optimizer

### 7.1 Formulation

**Decision variables** (5 × 24 = 120), directives applied as bounds:

| Var | Emitted as | Range | Directive that moves it |
|---|---|---|---|
| `g[h]` grid purchased | `grid_kwh` | `[0, gridcap[h]]` | `max_grid_window` |
| `s[h]` solar used | `solar_used_kwh` | `[0, eff[h]]` | `solar_reduction` |
| `chg[h]` charge | `battery_action`/`battery_kwh` | `[0, 0 if h∈nochg else max_charge]` | `no_charge_window` |
| `dis[h]` discharge | `battery_action`/`battery_kwh` | `[0, 0 if h∈nodis else max_discharge]` | `no_discharge_window` |
| `E[h]` energy after | `battery_energy_after_kwh` | `[max(base_min, reserve[h]), capacity]` | `minimum_battery_reserve` |

**Every directive is a bound.** No per-type branching inside the solver.

**Objective** (DR-12):
```
minimize  Σ  g[h] × tariff[h]
```

**Constraints** (49 total):
```
∀h:  g[h] + s[h] + dis[h] == demand[h] + chg[h]                  # DR-10 balance
∀h:  E[h] == (initial if h==0 else E[h-1]) + chg[h] - dis[h]     # DR-01/02/03
     E[23] == initial                                            # DR-11 neutrality
```

DR-04/05/06/07/08 are expressed as variable bounds, not rows.

### 7.2 Why LP

| Alternative | Why rejected |
|---|---|
| Brute force | grid amounts are continuous; even 1-kWh steps are astronomically many at 24 hours |
| Greedy heuristic | cannot sacrifice now for later — misses e.g. discharging at 6 BDT to make room for 5 BDT energy resold at 28; valid but costlier |
| DP | requires discretising battery level (approximate) and hand-coding each new directive type |
| **LP** | **exact, proven optimal, ~10 ms, directives are just bounds** |

Problem is linear throughout — verified: no efficiency term, no loss, no degradation, no quadratic, no demand/peak charge appears anywhere in the three source documents. `peak_grid_kwh` is reported (§10.1) but never billed (DR-12), so `max()` stays outside the model.

### 7.3 Infeasibility ladder

PRD GR-11 guarantees organizer scenarios are feasible, so `Infeasible` implies **our** extraction is wrong. Never return 500.

```python
for keep in range(n, -1, -1):               # n ≤ 3  ⇒  ≤ 8 subsets
    for subset in combinations(range(n), keep):
        if solve(subset).status == "Optimal":
            return plan, dropped
```

Measured: **208 of 208 infeasible fuzz cases rescued, 0 dead, worst case 83 ms.**

> **Honest scope:** dropping a directive does not save that case's score — the judge replays with its own ground truth, so a genuinely-real dropped directive still fails. What the ladder buys is a **valid 200 instead of a 500 or timeout**, protecting NFR-04, NFR-05 and every *other* case in the run.

---

## 8. Post-Processing

### 8.1 Netting (TR-8.1)

The LP is indifferent between `chg=50, dis=50` and `chg=0, dis=0` — identical cost. But §10.3 demands **exactly one** `battery_action` per hour. Observed in **16 hours across 3 of the 10 public cases**.

```python
net = chg[h] - dis[h]
action, kwh = ("charge", net) if net > TOL else \
              ("discharge", -net) if net < -TOL else ("idle", 0.0)
```

**Proof of cost-neutrality.** `chg` and `dis` appear in the model only as the difference `chg − dis`:
```
balance:  g + s + dis = d + chg   ⇒   g + s = d + (chg − dis) = d + net
battery:  E[h] = E[h−1] + chg − dis = E[h−1] + net
cost:     depends only on g, untouched
```
Rate limits survive (`net ≤ chg ≤ max_charge`). Windows survive (`no_charge` pins `chg=0`, so `net = −dis ≤ 0`, never a charge).

**This proof depends on there being no round-trip efficiency loss** — confirmed absent from all three documents. Were an efficiency term present, `chg` and `dis` would carry different weights, the clean difference would not hold, and netting would silently change the battery level.

### 8.2 Rounding & totals (TR-8.2)

```python
kwh = round(abs(net), 6)                                   # round FIRST
E   = round(E_prev + (kwh if charge else -kwh if discharge else 0), 6)   # accumulate the ROUNDED value
...
total_grid = sum(r["grid_kwh"] for r in plan)              # sum the PUBLISHED rows
total_cost = sum(r["grid_kwh"] * tariff[r["hour"]] for r in plan)
peak_grid  = max(r["grid_kwh"] for r in plan)
```

Two rules, both load-bearing for §12.3 ("totals match values recalculated from `hourly_plan`"):

1. **Round before accumulating.** Accumulating unrounded values while publishing rounded ones produced a 4e-3 gap on small-scale cases — 40% of the 0.01 tolerance budget. After the fix: **0.00e+00**.
2. **Never read cost from the solver.** `pulp.value(objective)` returns `None` when every tariff is 0, raising `TypeError` — **a 500 on a valid request**. PG §08 defines `quality_ratio` behaviour for zero-cost scenarios, so they exist (PRD AMB-06). Cost is always computed from the published rows.

### 8.3 Self-check (TR-8.3)

Before responding, replay our own answer through an independent checker mirroring §12.3 — balance, solar ceiling, battery bounds, rate limits, directive windows, neutrality, totals. Implements GR-08.

---

## 9. API Layer

### 9.1 `GET /health`

Returns `{"status":"ok"}` with 200. No LLM call, no solver call, no external dependency — must answer within 60 s of start (NFR-01) and stay cheap under repeated polling.

### 9.2 `POST /optimize-energy`

| Condition | Code |
|---|---|
| Success | 200 |
| Malformed JSON / schema violation | 400 |
| Internal error (must be rare) | 500, generic body, **no stack trace, no secrets** (PS §6.1, NFR-06) |

Request model enforces PRD §9: exactly 24 hours forming the set `{0..23}`; 1–3 non-empty notes; non-negative finite numbers; `minimum ≤ capacity`; `initial ≤ capacity`.

`scenario_id` echoed verbatim (§10.1 — worth 3 of the 10 API-contract points together with response shape).

---

## 10. Error Handling

| Failure | Handling | Response | Protects |
|---|---|---|---|
| Malformed request JSON | Pydantic rejects | **400** | API contract pts |
| LLM returns prose | `parse_llm` slices array; else retry | 200 | NFR-04 |
| LLM returns bad shape | repair → guardrail → retry once with the error text | 200 | GR-10 |
| Still bad after retry | those notes → `no_op`, solve with what validated | 200 | GR-10 |
| LLM API down / 429 / timeout | all notes → `no_op`, return plain optimal schedule | **200** | NFR-04, NFR-10 |
| LP `Infeasible` | subset-drop ladder (§7.3) | 200 | NFR-04 |
| Self-check fails | log, fall back to all-`no_op` solve | 200 | GR-08 |

**Design rule: degrade, never die.** A valid schedule missing one note beats a 500 — the note is worth a fraction of category 1; a 500 costs category 5 points *and* the whole case.

**Retry budget:** exactly one. Two LLM round-trips at ~3 s plus solver plus overhead must stay inside the 30 s hard timeout (NFR-02) with margin.

---

## 11. Performance Design

### 11.1 Latency budget (NFR-03: p95 ≤ 5 s for 3/3 points)

| Stage | Budget | Measured |
|---|---|---|
| HTTP + Pydantic | < 5 ms | — |
| **LLM call** | **≤ 4.5 s** | **1.57 s p95 measured** |
| Parse + repair + guardrail | < 2 ms | — |
| **LP solve** | **≤ 100 ms** | **10 ms (median), 39 simplex iterations** |
| Netting + rounding + self-check | < 5 ms | — |
| **Total p95 target** | **≤ 5 s** | **≈1.6 s projected** (3/3 latency points) |

**The LLM is ~99% of the latency.** Everything else is noise. This is why model selection (§3.2) is the single performance decision that matters.

### 11.2 Notes

- Single uvicorn worker — deterministic, no cross-request state.
- No caching of LLM results: hidden notes are unseen, so a cache would never hit during judging.
- CBC is invoked in-process; no subprocess spawn per request beyond PuLP's own.

---

## 12. Deployment

### 12.1 Container (DEL-05)

| Requirement | Implementation |
|---|---|
| Pullable, exact tag/digest | `docker push` with an explicit version tag; digest recorded in README |
| Expose documented port | `EXPOSE 8000` |
| Bind `0.0.0.0` | `uvicorn --host 0.0.0.0 --port 8000` |
| **No baked-in secrets** | API key supplied **only** via `-e GEMINI_API_KEY=...` at run time |
| Reaches `/health` | verified with the documented `docker run` before submission |

### 12.2 Environment variables

| Name | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | LLM credential. **Never committed. Never logged. Never in the image.** |
| `GEMINI_MODEL` | no | Model id override; defaults to the §3.2 selection |
| `PORT` | no | Defaults to 8000 |

README documents **names only, never values** (DEL-04, NFR-06).

### 12.3 Hosting

Public HTTPS endpoint, no auth, no VPN (NFR-07). Must stay reachable for the whole window (NFR-08) and be tested from outside the dev machine (NFR-09).

---

## 13. Security

| ID | Control | PRD |
|---|---|---|
| **TR-13.1** | `.env`, key files, and credentials in `.gitignore`; key delivered by environment variable only | NFR-06, PEN-10 |
| **TR-13.2** | 500 responses return a generic message — no stack trace, no exception text, no config | PS §6.1, NFR-06 |
| **TR-13.3** | Logs never contain the key, the raw prompt with credentials, or full request bodies | NFR-06 |
| **TR-13.4** | Docker image contains no secrets (verifiable by inspecting layers) | DEL-05 |
| **TR-13.5** | Only synthetic harness data processed; no external data source | NFR-12 |

---

## 14. Testing Strategy

### 14.1 Evidence already gathered

| Suite | Cases | Result |
|---|---|---|
| Public sample cases, exact cost + independent replay | 10 | **10/10 exact, 0.0000 BDT deviation** |
| Request validation edge cases (Layer 1) | 33 | **33/33** |
| Hostile LLM output (Layer 2) | 44 | **44/44** |
| Repair rescue + hard-reject leak check | 20 | **20/20** — 10 rescued, 0 leaks |
| Solver physics corner cases (Layer 3) | 16 | **16/16** |
| Numeric / tolerance (Layer 4) | 11 | **11/11**, drift 0.00e+00 |
| Randomised fuzz + infeasibility ladder | 3,000 | **0 replay failures, 208 rescued, 0 dead** |

### 14.2 Cross-validation

The replay checker is an **independent implementation** — it shares no code with the solver. Two further checks guard against both being wrong together:

1. **External oracle.** Organizer-computed optimal costs matched on all 10 public cases to 0.0000 BDT. Two independent codebases agreeing to the rupee means the constraint models agree.
2. **Brute force.** On a 3-hour reduction of the problem, exhaustive 1-kWh enumeration returns exactly the LP's answer (2750 = 2750).

### 14.3 Bugs this testing found

| # | Bug | Found by | Impact if shipped |
|---|---|---|---|
| 1 | Overlapping directives used last-wins, not tightest-wins | fuzz (2/400) | silently invalid cases |
| 2 | Zero tariff → `TypeError` from `pulp.value` | targeted corner case | **500 on a valid request** |
| 3 | Simultaneous charge + discharge in one hour | public-case audit | schema violation, 16 hours |
| 4 | Guardrail rejected recoverable notes | repair analysis | lost notes + invalid cases |
| 5 | Rounding drift (accumulate unrounded, publish rounded) | tolerance tests | totals mismatch near the limit |

### 14.4 Still untested at time of writing

- Concurrency / sustained load against the live endpoint
- Real LLM timeout and 429 behaviour end-to-end
- Docker pull/run from a clean machine
- **Prompt performance on genuinely unseen hidden phrasings** — irreducible; mitigated by §3.2's paraphrase benchmark

---

## 15. Repository Layout

```
gridwise/
├── app/
│   ├── main.py            FastAPI app, both endpoints          [§9]
│   ├── schemas.py         Pydantic request/response models     [§9.2]
│   ├── llm.py             prompt + Gemini call + retry         [§3]
│   ├── repair.py          unambiguous coercion                 [§4.2]
│   ├── guardrail.py       11 deterministic checks              [§5]
│   ├── apply.py           directives -> bounds, tightest-wins  [§6]
│   ├── optimizer.py       PuLP/CBC model + infeasibility ladder[§7]
│   ├── postprocess.py     netting, rounding, totals            [§8]
│   └── replay.py          self-check (judge mirror)            [§8.3]
├── tests/
│   ├── test_public_cases.py
│   ├── test_request_validation.py
│   ├── test_guardrail.py
│   ├── test_corner_cases.py
│   └── test_fuzz.py
├── samples/               public sample cases JSON
├── Dockerfile
├── requirements.txt
├── .gitignore             .env, *.key, __pycache__
└── README.md              [DEL-04]
```

---

## 16. Build Order

Matches the PRD §18 organizer-recommended priority, sequenced so the deterministic, provable work lands before the uncertain work.

| # | Task | Points unlocked | Why this order |
|---|---|---|---|
| 1 | FastAPI shell + schemas + `/health` | 10 (cat 4) + 2 (cat 5) | deterministic, testable offline |
| 2 | Optimizer + netting + rounding + replay | 25 (cat 2) + 10 (cat 3) | **already built and proven on all 10 cases** |
| 3 | **Dockerfile + README** | **20 (cat 6+7)** | pure checklist; never leave for the last 15 minutes |
| 4 | LLM + repair + guardrail | 25 (cat 1) | the uncertain half — gets all remaining time |
| 5 | Deploy + external test | 10 (cat 6) | NFR-07/08/09 |
| 6 | 3-minute video | tie-break only | zero base points |

> **Rationale.** Items 1–3 are 45 points of work that cannot fail in unpredictable ways. Item 4 is where the round is actually won or lost, so it should inherit every spare minute — which only happens if 1–3 are already done.

---

## 17. Traceability: TRD → PRD

| TRD section | Implements |
|---|---|
| §1 Architecture | FR-01…FR-07 |
| §3 LLM Interpreter | FR-01, FR-07, FR-20/21/22/23, NFR-03, NFR-10 |
| §4 Parse & Repair | GR-10, FR-16, PEN-02 mitigation |
| §5 Guardrail | GR-01…GR-06, GR-09, GR-10, FR-10…FR-17 |
| §6 Apply | FR-13, FR-30, §6.2 directive math, AMB-02 |
| §7 Optimizer | FR-05, FR-06, DR-01…DR-12, GR-11 |
| §8 Post-Process | §10.3 schema, §12.3 totals, DR-03, DR-11, AMB-06 |
| §8.3 Self-check | GR-08 |
| §9 API Layer | §8 contract, §9 request, §10 response, NFR-05 |
| §10 Error Handling | GR-10, NFR-04, NFR-05, PEN-09 |
| §11 Performance | NFR-01, NFR-02, NFR-03 |
| §12 Deployment | DEL-01, DEL-02, DEL-05, NFR-07…NFR-09 |
| §13 Security | NFR-06, PEN-10, DEL-03, DEL-05 |
| §14 Testing | §19 acceptance criteria (all) |
| §15 Repo Layout | DEL-03 |
| §16 Build Order | §18 recommended priority |
| §18 Compliance Notes | FR-18, FR-23, NFR-11, DEL-06, PEN-01, PEN-04…PEN-08 |
| §18.1 Ambiguity resolutions | AMB-01, AMB-03…AMB-07 |

---

## 18. Compliance Notes for Remaining Requirements

Requirements from the PRD that are satisfied by policy or by a cross-cutting control rather than by a single module.

| PRD ref | Requirement | How this design satisfies it |
|---|---|---|
| **FR-18** | A schedule that interprets a note correctly but does not apply it is still incorrect | The validated directive set is the **only** input to §6 Apply, which is the only source of solver bounds. There is no code path where an accepted directive fails to reach the model. §8.3 self-check re-verifies application against the plan before responding. |
| **FR-23** | Robust to paraphrase; do not hard-code public wording | No string matching against note text exists anywhere in the codebase — §3 is the sole interpreter. Public sample wording is used only as test fixtures (§14), never as logic. Verified by the §3.2 paraphrase benchmark, which contains no public-case phrasings. |
| **NFR-11** | No runtime training or fine-tuning | Inference-only API calls. No model weights, no training step, no warm-up job. Container starts and serves. |
| **DEL-06** | 3-minute video | Built last (§16 item 6). Content mirrors §1.1 pipeline diagram: problem → architecture → LLM/guardrail/optimizer flow → live `docker run` + two curl calls. Zero base points; tie-break only. |
| **PEN-01** | LLM absent from interpretation path ⇒ **not eligible** | Structural, not incidental: §6 Apply consumes only §5 Guardrail output, which consumes only §3 LLM output. Delete the LLM and the optimizer receives an empty directive set. Repository layout (§15) makes this inspectable — `llm.py` is the only producer of directives. |
| **PEN-04** | Energy-balance failure / unmet demand ⇒ case invalid | Balance is an **equality constraint** in the LP (§7.1), so no returned plan can violate it. Re-checked in §8.3. |
| **PEN-05** | Battery bound / transition / rate violation ⇒ case invalid | Encoded as variable bounds (§7.1); netting preserves them (§8.1 proof). Re-checked in §8.3. |
| **PEN-06** | Effective-solar overuse or negative values ⇒ case invalid | `s[h]` is bounded above by `eff[h]` and below by 0 (§7.1). All emitted quantities are non-negative by construction. Re-checked in §8.3. |
| **PEN-07** | Window/reserve/grid-cap violation ⇒ case invalid | Each is a bound (§6, §7.1). Re-checked in §8.3 against the same directives. |
| **PEN-08** | End-of-day neutrality violation ⇒ case invalid | `E[23] == initial` is an equality constraint (§7.1). §8.2 accumulates the **rounded** values so the published final row equals the constraint exactly. |

### 18.1 Ambiguity resolutions (PRD §20)

| PRD ref | Ambiguity | Technical handling |
|---|---|---|
| **AMB-01** | Guide §08 sentence on zero-optimal-cost `quality_ratio` is **truncated in the source PDF** | No implementation impact — we target `quality_ratio = 1` by returning proven-optimal plans. §8.2 additionally guarantees zero-cost scenarios do not crash. |
| **AMB-03** | Empty `hours` array not addressed by the spec | Guardrail check 8 rejects it → retry → `no_op` fallback (§5, §10). An empty window has no effect regardless. |
| **AMB-04** | `422` marked "Optional" for semantically invalid requests | Not used. All rejected requests return `400` (§9.2) for a single, consistent path. |
| **AMB-05** | p95 measurement window unspecified | Optimised per-request, not per-batch: §11.1 targets ≤ 5 s on **every** call, which satisfies any aggregation the judge chooses. |
| **AMB-06** | Zero-tariff / zero-cost hidden cases implied by the Guide's own `quality_ratio` rule | Handled explicitly — cost is never read from `pulp.value()` (§8.2). This was a real 500-causing bug, found and fixed (§14.3 bug 2). |
| **AMB-07** | Repository timing defers to an unpublished "official rulebook" | Follow PG §02/§04 literally (§12, §13). Operational, not technical — confirm with organizers if the rulebook is released. |

---

*End of TRD v1.0*
