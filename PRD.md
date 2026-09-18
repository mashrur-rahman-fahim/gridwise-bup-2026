# Product Requirements Document (PRD)
## GridWise — Smart Campus Energy Optimization Challenge
### BUP CSE Fest 2026 · Hackathon · Online Preliminary Round

| Field | Value |
|---|---|
| Document | PRD v1.0 |
| Round | Online Preliminary |
| Window | 7:00 PM – 11:00 PM (4 hours) |
| Challenge type | LLM-assisted energy scheduling and optimization |
| Required deliverable | One deployed, public HTTP API service |
| Health endpoint | `GET /health` |
| Main endpoint | `POST /optimize-energy` |
| Planning horizon | 24 hourly intervals (hours 0–23) |
| Operator notes | 1–3 natural-language notes per scenario |
| Response format | Structured JSON |
| Total score | 100 points (automated) |
| Data | 100% synthetic. No live campus, utility, billing, or personal data. |

---

## 0. Document Control & Source Authority

### 0.1 Canonical hierarchy

Per Problem Statement §12 and Participant Guide §04 (CANONICAL CONTRACT):

1. **Problem Statement** — canonical for: endpoint names, request/response fields, directive types, interpretation guardrails, battery behaviour, energy accounting, optimization validity rules.
2. **Participant Guide & Evaluation Rubric** — canonical for: deployment, repository policy, submission procedure, performance requirements, evaluation weights, penalties, tie-breakers.
3. **Public Sample Cases JSON** — worked examples for local validation only. **Not** the hidden judge set.

> If the Guide and the Problem Statement disagree on challenge behaviour, **the Problem Statement wins.**

### 0.2 Requirement ID scheme

| Prefix | Meaning |
|---|---|
| `FR-` | Functional requirement |
| `DR-` | Domain rule (energy/battery physics) |
| `GR-` | Guardrail requirement |
| `NFR-` | Non-functional requirement |
| `DEL-` | Deliverable |
| `PEN-` | Penalty / disqualifier |
| `AMB-` | Documented ambiguity + our resolution |

Every requirement carries a **Source** column citing the exact document and section.

---

## 1. Problem Context

BUP operates a smart campus powered by three sources:

- **Grid** — purchased electricity; hourly tariff varies across the day.
- **Rooftop solar** — free but only available in daylight hours; cannot be exported.
- **Battery energy storage system (BESS)** — stores energy; shifts it between hours; generates nothing.

The next 24 hours of demand, solar availability, and tariff are **given in the request**. Nothing is forecast or predicted.

Separately, campus operators send **1–3 short natural-language notes** describing temporary operating conditions that affect that same 24-hour window. Some notes change the schedule; others are realistic distractors that must be ignored.

**The system must:** understand the notes, convert relevant ones into structured directives, validate those directives deterministically, apply them to the optimization model, and return a valid low-cost 24-hour operating plan.

*Source: Problem Statement §01, §02.*

---

## 2. Objective & Success Definition

### 2.1 Primary objective

Build **one** HTTP API service that accepts a 24-hour energy scenario plus operator notes and returns **both**:

1. A machine-checkable **interpretation** of every operator note.
2. The final 24-hour **energy schedule**.

*Source: Problem Statement §02.*

### 2.2 Ordered success criteria

Per Problem Statement §05.2 and Guide §07 (SCORING PRINCIPLE), in strict priority order:

1. **Valid** — the schedule breaks no energy, battery, or directive rule.
2. **Correct interpretation** — each note maps to the right directive and values.
3. **Correct application** — the schedule actually obeys those directives.
4. **Low cost** — only then, minimize grid electricity cost.

> A low-cost schedule is **invalid** if it breaks any energy, battery, or operator-directive rule. Optimization credit is considered only after the case is valid.

---

## 3. Scope

### 3.1 In scope

- Natural-language interpretation of operator notes via an LLM.
- Deterministic validation of LLM output.
- 24-hour energy scheduling optimization.
- Two HTTP endpoints, exact names and schemas.
- Public deployment, Docker fallback image, README, 3-minute video.

### 3.2 Out of scope

| Excluded | Source |
|---|---|
| Grid export / selling energy back | PS §9.4 |
| Live campus, utility, billing, or personal data | PS §01 header, PG §04 |
| Any directive type outside the six listed | PS §04, §05.1 |
| Runtime training or fine-tuning during evaluation | PG §03 |
| Forecasting demand/solar/tariff (all supplied) | PS §01 |
| Endpoints beyond `/health` and `/optimize-energy` | PS §06 |

---

## 4. Actors

| Actor | Description |
|---|---|
| **Judge harness** | Automated script. POSTs hidden scenarios to the public base URL, reads JSON, replays and scores. The only consumer. No human UI is required or scored. |
| **Campus operator (fictional)** | Author of the natural-language notes inside each scenario. Does not interact with the system. |
| **Organizer artifact reviewer** | Checks Docker image, README reproducibility, and (on ties) the video. |

---

## 5. Functional Requirements

### 5.1 Core pipeline

| ID | Requirement | Source |
|---|---|---|
| **FR-01** | Interpret **every** operator note using an LLM or other language-capable generative model. | PS §02 |
| **FR-02** | Convert relevant notes into exactly one of the six supported directive types. | PS §02, §04.1 |
| **FR-03** | Mark irrelevant notes as `no_op` rather than inventing an energy rule. | PS §02 |
| **FR-04** | Validate interpreted directives deterministically **before** sending them to the optimizer. | PS §02, §08; PG §03 |
| **FR-05** | Produce a schedule satisfying all normal GridWise rules **and** every applicable directive. | PS §02 |
| **FR-06** | Minimize total grid electricity cost **after** correctness is satisfied. | PS §02, §05.2 |
| **FR-07** | The LLM's structured interpretation **must be part of the path that produces the optimization constraints.** | PS §02 (LLM REQUIREMENT); PG §04 |

> **FR-07 is a hard eligibility gate.** Using an LLM only for `plan_summary`, documentation, or cosmetic text **does not satisfy** the requirement. Hard-coded phrase matching as the sole interpreter is **not compliant**. Automated and artifact verification may inspect the repository/architecture to confirm compliance.
> *Source: PS §02; PG §04, §09.*

### 5.2 Operator-note clauses

| ID | Requirement | Source |
|---|---|---|
| **FR-10** | Every operator note produces **exactly one** `directive_interpretation` entry. | PS §05.1 |
| **FR-11** | Entries returned in `note_index` order: `0, 1, ... N-1`. No missing, duplicate, or out-of-order mappings. | PS §05.1, §11.1; PG §08 |
| **FR-12** | Only the six directive types in §04 are accepted. | PS §05.1 |
| **FR-13** | Relevant notes must be applied to the optimization **before** scheduling. | PS §05.1 |
| **FR-14** | Irrelevant notes use `applies = false`, `directive_type = "no_op"`, `structured_adjustment = null`. | PS §05.1 |
| **FR-15** | For every non-`no_op` directive, `applies` **must be** `true`. `no_op` is the **only** directive allowed with `applies = false`. | PS §05.1 |
| **FR-16** | Every `hours` array must contain **unique integers 0–23 in ascending order**. | PS §05.1, §08 |
| **FR-17** | The LLM must not invent demand, solar, tariff, battery limits, or unsupported directive types. | PS §05.1, §08 |
| **FR-18** | A schedule that interprets a note correctly but **does not apply it** is still incorrect. | PS §05.1 |

### 5.3 Time & value normalization

| ID | Requirement | Source |
|---|---|---|
| **FR-20** | Time windows are **whole-hour, start-inclusive, end-exclusive**. "1 PM to 3 PM" → `[13, 14]`. | PS §05.1; PG §08 |
| **FR-21** | For `solar_reduction`, `factor` is the **usable fraction that remains**, not the fraction removed. An 80% reduction → `factor = 0.2`. "drops to 25%" → `factor = 0.25`. | PS §05.1; PG §08 |
| **FR-22** | Percentage-of-capacity reserves must be resolved to absolute kWh. (Public SAMPLE-03: "50% of battery capacity" with `capacity_kwh = 200` → `minimum_energy_kwh = 100`.) | Sample Cases SAMPLE-03 |
| **FR-23** | The same underlying directive may be paraphrased differently in hidden cases; the system must resolve equivalent phrasings to the same directive. Do **not** hard-code public wording. | PS §04, §11.4; PG §08, §10 |

**Worked paraphrase set (all three → `solar_reduction`, `hours [13,14]`, `factor 0.2`):**
- "PV production will drop to about 20% between 13:00 and 15:00."
- "Panel washing from one until three will leave roughly one-fifth of normal solar output."
- "Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window."

*Source: PS §11.4.*

---

## 6. Directive Catalogue

### 6.1 The six supported types

| Directive type | Meaning | Required `structured_adjustment` |
|---|---|---|
| `solar_reduction` | Reduce usable solar during specific hours. | `{"hours":[...], "factor": number}` |
| `minimum_battery_reserve` | Keep battery energy at or above a required level. | `{"hours":[...], "minimum_energy_kwh": number}` |
| `no_charge_window` | Battery charging unavailable during specific hours. | `{"hours":[...]}` |
| `no_discharge_window` | Battery discharging unavailable during specific hours. | `{"hours":[...]}` |
| `max_grid_window` | Grid import may not exceed a stated amount during specific hours. | `{"hours":[...], "max_grid_kwh": number}` |
| `no_op` | Note does not affect the current 24-hour schedule. | `null` |

*Source: PS §04.1.*

### 6.2 Deterministic effect on the optimization model

| Directive | Effect used by the optimizer | Source |
|---|---|---|
| `solar_reduction` | `effective_solar[h] = original_solar[h] * factor` for each listed hour | PS §5.3 |
| `minimum_battery_reserve` | `battery_energy_after_kwh[h] >= max(base minimum_energy_kwh, directive minimum_energy_kwh)` for each listed hour | PS §5.3 |
| `no_charge_window` | battery charge amount = `0` in the listed hours | PS §5.3 |
| `no_discharge_window` | battery discharge amount = `0` in the listed hours | PS §5.3 |
| `max_grid_window` | `grid_kwh[h] <= max_grid_kwh` in the listed hours | PS §5.3 |
| `no_op` | No change to the optimization model | PS §5.3 |

### 6.3 Reference interpretation examples

| Operator note | Expected interpretation |
|---|---|
| "Solar output will drop to about 20% from 1 PM to 3 PM." | `solar_reduction`; hours `[13,14]`; factor `0.2` |
| "Do not charge the battery between 2 PM and 4 PM." | `no_charge_window`; hours `[14,15]` |
| "Keep at least 120 kWh in reserve from 6 PM until 9 PM." | `minimum_battery_reserve`; hours `[18,19,20]`; `120` kWh |
| "The cafeteria menu changes tomorrow." | `no_op` |

*Source: PS §04.2.*

### 6.4 Directive combination rule

**FR-30** — Where multiple directives of the same type affect the same hour, the **most restrictive** value applies: `max()` for `minimum_battery_reserve`; `min()` for `max_grid_kwh` and for resulting effective solar.
*Basis: PS §5.3 uses `max(base minimum_energy_kwh, directive minimum_energy_kwh)`, establishing tightest-wins semantics. Applied consistently across constraint types.*

---

## 7. Domain Rules — Energy & Battery

These are hard physical rules. The judge **independently replays** the final schedule hour by hour using the effective solar and any additional operator directives.

| ID | Rule | Formula | Source |
|---|---|---|---|
| **DR-01** | Battery charge | `E_after = E_before + battery_kwh` | PS §9.1 |
| **DR-02** | Battery discharge | `E_after = E_before - battery_kwh` | PS §9.1 |
| **DR-03** | Battery idle | `E_after = E_before` **and** `battery_kwh = 0` | PS §9.1 |
| **DR-04** | Battery bounds | `minimum_energy_kwh <= E_after <= capacity_kwh` | PS §9.2 |
| **DR-05** | Active reserve directive may raise the minimum above the base for those hours | `E_after[h] >= max(base_min, directive_min)` | PS §9.2, §5.3 |
| **DR-06** | Hourly charge limit | `battery_kwh <= max_charge_kwh_per_hour` when action = charge | PS §9.3 |
| **DR-07** | Hourly discharge limit | `battery_kwh <= max_discharge_kwh_per_hour` when action = discharge | PS §9.3 |
| **DR-08** | Solar usage ceiling | `0 <= solar_used_kwh <= effective_solar_kwh` | PS §9.4 |
| **DR-09** | Unused solar is **curtailed**. Grid export is not part of this challenge. | — | PS §9.4 |
| **DR-10** | Energy balance, every hour | `grid_kwh + solar_used_kwh + battery_discharge_kwh = demand_kwh + battery_charge_kwh` | PS §9.5 |
| **DR-11** | End-of-day neutrality | `final battery_energy_after_kwh = initial_energy_kwh` | PS §9.6 |
| **DR-12** | Optimization objective | `total_cost_bdt = SUM(grid_kwh[h] * tariff_bdt_per_kwh[h])` for `h = 0..23` | PS §5.2 |

> **Why DR-11 exists:** the starting battery may shift energy between hours, but cannot be consumed as a free one-time source by ending the day at a lower state of charge.
> *Source: PS §09, WHY THIS RULE EXISTS callout.*

**Implication of DR-12:** the bill counts **grid energy only**. Solar and battery contribute no cost. There is **no demand charge or peak charge** — `peak_grid_kwh` is reported but never billed.

---

## 8. API Contract

The judge harness exercises **only** these endpoints. **Endpoint names must match exactly.**

| Endpoint | Requirement | Source |
|---|---|---|
| `GET /health` | Return HTTP 200 with a JSON object containing `status = "ok"` when the service is ready. | PS §06 |
| `POST /optimize-energy` | Accept one scenario JSON object; return one interpretation + optimization-plan JSON object. | PS §06 |

### 8.1 Health response

```json
{ "status": "ok" }
```
*Source: PS §6.2.*

### 8.2 HTTP response codes

| Code | Meaning | Source |
|---|---|---|
| `200` | Successful health response or successful optimization response. | PS §6.1 |
| `400` | Malformed JSON or structurally invalid request. | PS §6.1 |
| `422` | **Optional.** Semantically invalid but well-formed request. | PS §6.1 |
| `500` | Controlled internal error. **Do not expose secrets or raw stack traces.** | PS §6.1 |

---

## 9. Request Schema — `POST /optimize-energy`

Accepts one JSON object. The `hours` array must contain **exactly 24 entries** for hours 0 through 23. `operator_notes` must contain **1–3 non-empty** natural-language strings, each referring to the same 24-hour scenario.

### 9.1 Top-level fields

| Field | Type | Requirement |
|---|---|---|
| `scenario_id` | string | Unique synthetic scenario identifier. |
| `operator_notes` | array[1..3] of string | Natural-language campus operator notes to interpret. |
| `hours` | array[24] | Hourly demand, solar availability, and grid tariff. |
| `battery` | object | Battery capacity, starting energy, reserve, and hourly limits. |

### 9.2 Hour entry

| Field | Type | Meaning |
|---|---|---|
| `hour` | integer | Unique integer from 0 to 23. |
| `demand_kwh` | number | Campus demand that must be supplied in this hour. |
| `solar_kwh` | number | **Base** solar energy available **before** operator-note adjustments. |
| `tariff_bdt_per_kwh` | number | Grid electricity price for this hour. |

### 9.3 Battery object

| Field | Meaning |
|---|---|
| `capacity_kwh` | Maximum energy the battery can store. |
| `initial_energy_kwh` | Battery energy at the start of hour 0. |
| `minimum_energy_kwh` | Base reserve level the battery must never go below. |
| `max_charge_kwh_per_hour` | Maximum energy that may be added in one hour. |
| `max_discharge_kwh_per_hour` | Maximum energy that may be removed in one hour. |

### 9.4 Example request shape

```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
    "... 22 more hourly entries ...",
    {"hour": 23, "demand_kwh": 200, "solar_kwh": 0, "tariff_bdt_per_kwh": 9}
  ],
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
```
*Source: PS §07.*

---

## 10. Response Schema

A successful `POST /optimize-energy` response must include **both** the operator-note interpretation **and** the final 24-hour schedule.

### 10.1 Top-level response fields

| Field | Type | Requirement |
|---|---|---|
| `scenario_id` | string | **Must match** the request `scenario_id`. |
| `directive_interpretation` | array | One machine-checkable interpretation entry for **every** operator note. |
| `hourly_plan` | array[24] | One plan entry for every hour 0 through 23. |
| `total_grid_kwh` | number | Sum of `grid_kwh` across all 24 hours. |
| `total_cost_bdt` | number | Calculated total grid electricity cost. |
| `peak_grid_kwh` | number | Maximum hourly `grid_kwh` in the returned plan. |
| `plan_summary` | string | Short human-readable explanation of the final strategy. |

### 10.2 Directive interpretation entry

| Field | Requirement |
|---|---|
| `note_index` | Zero-based index of the corresponding `operator_notes` entry. |
| `applies` | `true` for every applicable non-`no_op` directive; `false` **only** for `no_op`. |
| `directive_type` | One supported directive type from §6.1. `no_op` is required when `applies = false`. |
| `structured_adjustment` | Exact machine-checkable object required by §6.1, or `null` **only** for `no_op`. |
| `explanation` | Short explanation of the interpretation. **Not matched byte-for-byte.** |

### 10.3 Hourly plan entry

| Field | Allowed value / meaning |
|---|---|
| `hour` | Integer 0 through 23. |
| `grid_kwh` | **Non-negative** grid energy purchased in this hour. |
| `solar_used_kwh` | Solar energy used in this hour; **cannot exceed effective solar**. |
| `battery_action` | **Exactly one of:** `charge`, `discharge`, `idle`. |
| `battery_kwh` | **Non-negative magnitude** of the battery action. **Must be 0 when `idle`.** |
| `battery_energy_after_kwh` | Battery energy immediately after completing this hour. |

### 10.4 Example interpretation fragment

```json
"directive_interpretation": [
  {
    "note_index": 0,
    "applies": true,
    "directive_type": "solar_reduction",
    "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
    "explanation": "Solar availability is reduced during panel cleaning."
  },
  {
    "note_index": 2,
    "applies": false,
    "directive_type": "no_op",
    "structured_adjustment": null,
    "explanation": "This note does not affect today's energy schedule."
  }
]
```
*Source: PS §10.*

---

## 11. Guardrail Requirements

> **LLM output must be treated as untrusted structured data until deterministic validation passes.**
> *Source: PS §08.*

| ID | Guardrail | Requirement | Source |
|---|---|---|---|
| **GR-01** | Allowed types | `directive_type` must be one of the six values in §6.1. | PS §08 |
| **GR-02** | Note mapping | `note_index` must identify an existing operator note; each note must appear **once**. | PS §08 |
| **GR-03** | Hours | Every listed hour must be a **unique integer 0–23**, returned in **ascending order**. | PS §08 |
| **GR-04** | Solar factor | For `solar_reduction`, `factor` must be **between 0 and 1 inclusive**. | PS §08 |
| **GR-05** | Battery reserve | Reserve values must be **finite, non-negative, and not exceed battery capacity**. | PS §08 |
| **GR-06** | Grid cap | `max_grid_kwh` must be **finite and non-negative**. | PS §08 |
| **GR-07** | No invention | Interpretation may not change base demand, tariff, or battery parameters unless a supported directive explicitly allows it. | PS §08 |
| **GR-08** | Final replay | The completed schedule is replayed after optimization to verify every extracted directive was actually followed. | PS §08 |
| **GR-09** | `applies` semantics | `no_op` → `applies = false` + `structured_adjustment = null`. Every other directive → `applies = true` + adjustment matching the required shape. | PS §08 |
| **GR-10** | Safe failure | If the LLM returns malformed or unsupported structured output, handle it in a **controlled** way. The service **must not silently invent a new directive type or crash**. | PS §08 (SAFE FAILURE) |

**GR-11 (organizer guarantee, not our obligation):** valid organizer scoring scenarios have a feasible ground-truth interpretation and will not require mutually contradictory hard directives. *Source: PS §05.1, §08.*
*Implication: infeasibility at runtime indicates a bad extraction on our side, not a bad scenario — and must still be handled per GR-10.*

---

## 12. Validation & Hidden Evaluation

Hidden evaluation checks **both** language understanding **and** energy optimization. Teams must not assume only `total_cost_bdt` or the free-text explanation is checked.
*Source: PS §11.*

### 12.1 Interpretation checks (PS §11.1)

- Correctly identify whether each note applies or is `no_op`.
- Return the correct directive type.
- Extract the correct hours and numeric values within the allowed tolerance.
- Remain robust when the same directive is paraphrased differently.
- One entry per note in `note_index` order, no missing or duplicate mappings.
- Match the required `structured_adjustment` shape for the selected type.
- Use `applies = false` only for `no_op`.

### 12.2 Downstream application checks (PS §11.2)

- The judge **recomputes effective solar** after `solar_reduction` directives.
- The judge verifies reserve, no-charge, no-discharge, and grid-cap directives **directly against `hourly_plan`**.
- **Correct extraction without correct downstream application does not pass the case.**

### 12.3 GridWise consistency checks (PS §11.3)

- `hourly_plan` contains exactly 24 unique hours, 0 through 23.
- Required numeric values are finite and non-negative.
- Battery transitions, capacity, minimum energy, and hourly rate limits are valid.
- Solar usage never exceeds effective available solar.
- The energy-balance equation holds every hour.
- Final battery energy equals initial battery energy.
- `total_grid_kwh`, `total_cost_bdt`, and `peak_grid_kwh` **match values recalculated from `hourly_plan`**.

### 12.4 Equivalent schedules accepted

> **NO BYTE-FOR-BYTE MATCHING.** Equivalent valid optimal schedules may differ. The judge evaluates structured interpretation, directive application, schedule validity, and recalculated cost — **not** exact JSON equality with one reference plan.
> *Source: PS §11.4.*

### 12.5 Numeric tolerance

**Absolute tolerance of 0.01 kWh or 0.01 BDT**, unless the official judge package specifies stricter.
*Source: PS §11.5; PG §08.*

### 12.6 Hidden test characteristics (PG §10)

- Hidden case list, wording, distribution, and expected answers are **not published**.
- Each valid hidden scenario contains 1–3 synthetic operator notes; each maps to **exactly one** supported directive type or `no_op`.
- Hidden notes **do not require unpublished directive types**.
- The same directive may be paraphrased with different wording, whole-hour time expressions, percentages, or equivalent numeric descriptions. **Do not hard-code public phrases.**
- Hidden cases also vary demand, solar, tariff, battery state, reserve/rate limits, and directive combinations.

---

## 13. Non-Functional Requirements

| ID | Requirement | Threshold | Source |
|---|---|---|---|
| **NFR-01** | Health readiness | `GET /health` returns `{"status":"ok"}` **within 60 seconds** of service start. | PG §08 |
| **NFR-02** | Per-request timeout | `POST /optimize-energy` must complete **within 30 seconds**. Responses beyond the timeout are **failures**. | PG §08 |
| **NFR-03** | p95 latency | `p95 ≤ 5s` → 3/3 points; `>5s–15s` → 2/3; `>15s–30s` → 1/3; `>30s` → 0/3 and timed-out requests are failures. | PG §08 |
| **NFR-04** | Failure rate | Valid requests must not return 5xx, invalid JSON, or no response. Service must remain stable across repeated hidden cases. | PG §08 |
| **NFR-05** | Malformed input handling | Return a controlled error or safe failure. Do not crash or invent an unsupported directive. | PG §08 |
| **NFR-06** | Secret handling | **No** API keys, tokens, raw secret values, or sensitive stack traces in repo, logs, or responses. | PG §04, §08 |
| **NFR-07** | Public reachability | Judge must call both endpoints from the submitted base URL. **No login, dashboard, manual approval, VPN, or private-network access.** | PG §03 |
| **NFR-08** | Sustained availability | Service must remain reachable **throughout the evaluation window**, including repeated LLM-backed requests. | PG §03 |
| **NFR-09** | External testing | Both endpoints must be tested **from outside the development environment** before submitting. | PG §03 |
| **NFR-10** | LLM availability | The model used for `operator_notes` must be available during judging. **The team owns keys, quota, rate limits, cost, and provider availability.** Judges will not repair an unavailable dependency. | PG §03, §04 |
| **NFR-11** | No runtime training | Do not require long training or fine-tuning jobs during evaluation. | PG §03 |
| **NFR-12** | Synthetic data only | Use only the synthetic challenge data supplied by the harness. | PG §04 |

---

## 14. Deliverables

| ID | Deliverable | Requirement | Source |
|---|---|---|---|
| **DEL-01** | **API service** | **One** HTTP API service exposing both required endpoints. Submit one service, not separate deployments. | PG §02 |
| **DEL-02** | **Public endpoint** | Base URL reachable by the judge for `GET /health` and `POST /optimize-energy`. | PG §02 |
| **DEL-03** | **GitHub repository** | Created **after question reveal**. **Private during** the event. **Public after** the submission deadline for evaluation. All source code and dependency/configuration files. | PG §02, §04 |
| **DEL-04** | **README.md** | Self-contained. Must enable organizers to run and test locally **without team assistance**. | PG §02, §03 |
| **DEL-05** | **Docker fallback image** | Tested, **pullable** registry reference with **exact tag or digest**. Must expose the documented service port, **bind to `0.0.0.0`**, and contain **no baked-in secrets**. Must remain pullable during evaluation. | PG §02, §08 |
| **DEL-06** | **3-minute video** | Maximum 3:00. Explains problem, architecture overview, solution approach, LLM → guardrails → optimizer flow, and how the system is run/tested. MP4 upload or organizer-accessible link. Production-quality editing not required. | PG §02, §08 |

### 14.1 README required contents (DEL-04 detail)

Per PG §02, §03, §07, §08 and the final pre-submit checklist:

- [ ] Source setup / clean-environment quickstart (clone/pull → configure → install or pull image → start → `/health` → one public sample)
- [ ] Required **environment-variable names** (names only — **never values**)
- [ ] Model/provider or local model identifier
- [ ] The LLM's role in the pipeline
- [ ] Guardrails description
- [ ] Optimizer / solver used
- [ ] Exact run command
- [ ] `/health` curl example
- [ ] `/optimize-energy` curl example with sample request/response
- [ ] Public-sample test command **and expected result**
- [ ] Dependencies, with **all external tools and libraries credited**
- [ ] Known limitations
- [ ] Secret-handling guidance
- [ ] Docker pull/run fallback instructions

---

## 15. Evaluation Model

### 15.1 Structure

- **Primary evaluation: 100 points, automated.** Scores core API behaviour, LLM directive interpretation, directive application, optimization quality, schema correctness, performance, and reliability. Deployment/Docker and documentation are checked against fixed reproducibility criteria using the submitted artifacts.
- **The 3-minute video contributes NO base points.** It is reviewed **only** to resolve tied total scores.

*Source: PG §06.*

### 15.2 Seven scoring categories

| # | Category | Points | Breakdown | Source |
|---|---|---|---|---|
| 1 | **LLM Directive Interpretation** | **25** | 5 relevance/`no_op` + 5 `directive_type` + 5 affected hours + 5 numeric values / required `structured_adjustment` shape + 5 paraphrase robustness across related hidden notes | PG §07 |
| 2 | **Directive Application & Constraint Correctness** | **25** | 10 organizer-ground-truth directive application + 5 hourly energy balance / effective-solar validity + 5 battery transitions/bounds/rate limits + 5 action consistency / end-of-day neutrality / non-negative values | PG §07 |
| 3 | **Optimization Quality** | **10** | Cost-quality score over optimization hidden cases. Invalid cases receive **zero**. | PG §07 |
| 4 | **API Contract & Schema** | **10** | 2 endpoints/status behaviour + 2 request validation + 3 `directive_interpretation` schema/order/types + 3 `hourly_plan`/top-level response schema and `scenario_id` echo | PG §07 |
| 5 | **Performance & Reliability** | **10** | 2 health readiness + 3 p95 latency + 3 valid-request stability/failure rate + 2 controlled malformed/model-provider failure handling and secret safety | PG §07 |
| 6 | **Deployment & Docker Fallback** | **10** | 3 live endpoint reachability + 4 working pullable Docker fallback image reaching `/health` via documented command + 2 clean startup/reproducibility from submitted instructions + 1 no judge debugging/manual code changes required | PG §07 |
| 7 | **Documentation & Local Reproducibility** | **10** | 3 clean local quickstart from fresh environment + 2 environment/configuration/model-provider documentation + 2 public-sample test procedure and expected result + 1 LLM/guardrail/optimizer architecture explanation + 1 Docker pull/run fallback instructions + 1 dependencies, limitations, and secret-handling guidance | PG §07 |
| | **TOTAL** | **100** | | |

### 15.3 Optimization score formula

```
quality_ratio            = min(1, organizer_optimal_cost / recalculated_team_cost)
Optimization Quality     = 10 × average(quality_ratio across all optimization hidden cases)
```

Special cases:
- Both `organizer_optimal_cost` and `recalculated_team_cost` within tolerance of 0 → `quality_ratio = 1`.
- `organizer_optimal_cost` within tolerance of 0 but team cost above tolerance → **see AMB-01**.
- **Invalid case → `quality_ratio = 0`.**

*Source: PG §07, §08.*

### 15.4 Strategic implication

> **50 of 100 points depend on correctly understanding and obeying the English notes** (categories 1 + 2).
> **20 points are non-algorithmic checklist work** (categories 6 + 7 — Docker and README).
> **Only 10 points are cost optimization**, and a valid-but-naive plan already earns most of them.

---

## 16. Penalties & Disqualifiers

| ID | Violation | Penalty | Source |
|---|---|---|---|
| **PEN-01** | Required LLM absent from the operator-note interpretation path, or AI used only for `plan_summary`/documentation | **Fails the mandatory challenge requirement; not eligible for the final preliminary shortlist** | PG §09 |
| **PEN-02** | Relevant note interpreted incorrectly or marked `no_op` | Interpretation credit lost for the affected note/case. Schedule still checked separately against the true directive. | PG §09 |
| **PEN-03** | Applicable ground-truth directive not reflected in `hourly_plan` | Affected hidden case **invalid** for directive-application scoring; **no optimization credit** for that case | PG §09 |
| **PEN-04** | Energy-balance failure or unmet hourly demand | Case invalid; no optimization credit | PG §09 |
| **PEN-05** | Battery bound, transition, charge-rate, or discharge-rate violation | Case invalid; no optimization credit | PG §09 |
| **PEN-06** | Effective-solar overuse or impossible/negative energy values | Case invalid; no optimization credit | PG §09 |
| **PEN-07** | `no_charge_window`, `no_discharge_window`, minimum reserve, or `max_grid_window` violation | Case invalid; no optimization credit | PG §09 |
| **PEN-08** | End-of-day battery energy does not return to initial level | Case invalid; no optimization credit | PG §09 |
| **PEN-09** | Reported totals disagree with `hourly_plan`, or repeated critical invalidity | Recalculation / scoring deduction; **repeated failures may block qualification eligibility** | PG §09 |
| **PEN-10** | Secrets committed to repo or exposed in logs/responses | Loses secret-safety points (part of category 5) | PG §04, §08 |

> **GROUND TRUTH BEFORE COST:** the judge first checks the organizer ground-truth directive, its downstream application, and normal GridWise constraints. **Only then** is optimization quality scored for that hidden case.
> *Source: PG §09.*

---

## 17. Tie-Break Order

Applied only when teams finish with the same total score.

| Priority | Tie-breaker |
|---|---|
| 1 | **3-minute Architecture & Solution Video** |
| 2 | Directive Application & Constraint Correctness |
| 3 | LLM Directive Interpretation |
| 4 | Optimization Quality |
| 5 | API/schema validity |
| 6 | Reliability and deployment stability |
| 7 | Documentation & local reproducibility |
| 8 | Exceptional engineering / verification (robust guardrails, fallbacks, caching, testing, implementation quality) |

*Source: PG §10.*

---

## 18. Recommended Build Priority

Organizer-recommended order (PG §11):

| Priority | Focus |
|---|---|
| 1 | Exact API & JSON Contract |
| 2 | LLM Operator-Note Interpretation |
| 3 | Deterministic Guardrails |
| 4 | Directive Application & Energy Correctness |
| 5 | Optimization Quality |
| 6 | Reliability, Deployment & Docker Fallback |
| 7 | Documentation & Local Reproducibility |
| 8 | 3-minute Video (tie-break readiness only) |

---

## 19. Acceptance Criteria

The solution is complete when **all** of the following hold:

### 19.1 Contract
- [ ] `GET /health` reachable, returns `{"status":"ok"}` within 60s of start.
- [ ] `POST /optimize-energy` reachable externally, accepts 1–3 `operator_notes` with the exact request schema.
- [ ] `scenario_id` echoed exactly.
- [ ] Malformed JSON → `400`. Never `500` on a valid request.

### 19.2 Interpretation
- [ ] Exactly one `directive_interpretation` entry per note, in `note_index` order.
- [ ] `no_op` → `applies = false` + `structured_adjustment = null`.
- [ ] All other directives → `applies = true` + exact required shape.
- [ ] `hours` unique integers 0–23 ascending.
- [ ] End-exclusive windows; `factor` = fraction remaining; percent-of-capacity resolved to kWh.

### 19.3 Guardrails
- [ ] LLM output deterministically validated before optimization.
- [ ] Invalid model output cannot silently invent constraints.
- [ ] Malformed model output handled without crash.

### 19.4 Schedule
- [ ] `hourly_plan` obeys organizer-ground-truth directives plus energy balance, effective-solar, battery bounds, rate limits, grid cap, and end-of-day neutrality.
- [ ] `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh` match values recalculated from `hourly_plan`.
- [ ] All 10 public sample cases pass an independent replay.

### 19.5 Deployment & documentation
- [ ] Repo created after reveal, private during, public after deadline.
- [ ] README self-contained with clean quickstart; no committed secrets.
- [ ] Docker image pullable by exact tag/digest; documented command reaches `/health`; port exposed; binds `0.0.0.0`; no baked-in secrets.
- [ ] Video accessible, ≤ 3:00, covers problem → architecture → LLM/guardrail/optimizer flow → run/test.

---

## 20. Documented Ambiguities & Resolutions

| ID | Ambiguity | Our resolution | Risk |
|---|---|---|---|
| **AMB-01** | **The Participant Guide §08 sentence "If organizer_optimal_cost is within tolerance of 0 but team cost is above tolerance, quality_ratio ___" is TRUNCATED in the source PDF.** The value is never stated. | Assume `quality_ratio = 0` for that case (the only reading consistent with `min(1, 0/x) = 0`). No action required from us beyond producing optimal plans. | Low — we target `quality_ratio = 1` regardless. |
| **AMB-02** | Behaviour when two directives of the same type overlap on the same hour is not explicitly stated. | Apply **tightest-wins** (`max` for reserve, `min` for grid cap and effective solar), extrapolating PS §5.3's `max(base, directive)` rule. | Low — and the safe direction: over-constraining stays valid, under-constraining does not. |
| **AMB-03** | Whether `hours` arrays may be empty is not stated. | Treat an empty `hours` array as invalid model output → retry → `no_op` fallback. An empty window has no effect anyway. | Low |
| **AMB-04** | `422` is marked "Optional" for semantically invalid but well-formed requests. | Use `400` for all rejected requests for consistency; `422` is not required. | Low |
| **AMB-05** | The scored p95 latency window (per-case vs across the whole run) is not specified. | Optimise for p95 ≤ 5s on every request. | Low |
| **AMB-06** | Whether hidden cases include zero-tariff hours is not stated, but PG §08 defines `quality_ratio` behaviour for zero-cost scenarios — implying they exist. | Handle zero tariffs and zero total cost without error. | Medium — must not crash. |
| **AMB-07** | Exact repository-timing rules defer to "the official rulebook", which is not in this document pack. | Follow PG §02/§04 literally: create after reveal, private during, public after deadline. Confirm with organizers if the rulebook is published. | Medium |

---

## 21. Requirement Traceability Summary

| Source section | Covered by |
|---|---|
| PS §01 Scenario | §1 |
| PS §02 What You Are Building | FR-01…FR-07, §2 |
| PS §03 End-to-End Flow | §2.2, TRD architecture |
| PS §04 Directives | §6.1, §6.3 |
| PS §05.1 Clauses | FR-10…FR-23 |
| PS §05.2 Objective | DR-12 |
| PS §05.3 Directive math | §6.2 |
| PS §06 API Contract | §8 |
| PS §07 Request Schema | §9 |
| PS §08 Guardrails | GR-01…GR-11 |
| PS §09 Battery & Energy | DR-01…DR-11 |
| PS §10 Response Schema | §10 |
| PS §11 Validation & Hidden Eval | §12 |
| PS §12 Canonical note | §0.1 |
| PG §02 Deliverables | DEL-01…DEL-06 |
| PG §03 Technical & Deployment | NFR-07…NFR-11, DEL-04 |
| PG §04 LLM/Tech/Security/Repo | FR-07, NFR-06, NFR-10, NFR-12, DEL-03 |
| PG §05 Testing checklist | §19 |
| PG §06 Evaluation model | §15.1 |
| PG §07 Scoring rubric | §15.2 |
| PG §08 Quality metrics | NFR-01…NFR-06, §12.5, §15.3 |
| PG §09 Violations & penalties | PEN-01…PEN-10 |
| PG §10 Hidden tests & tie-breakers | §12.6, §17 |
| PG §11 Quick reference | §18, §19 |

---

*End of PRD v1.0*
