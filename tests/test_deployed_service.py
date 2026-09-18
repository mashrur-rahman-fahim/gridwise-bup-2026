"""Exercises the actual LLM interpreter against the LIVE deployment.

Every other test in this suite either feeds ground truth straight into solve()
(test_public_cases.py, test_numeric.py, test_corner_cases.py) or hand-crafts
model-output JSON to test the guardrail directly (test_guardrail.py) or fuzzes
the optimizer with randomised *directives*, never real notes (test_fuzz.py).
None of them ever sends real English text through app.llm.interpret() and
checks the result. That's the blind spot the judge's hidden cases sit in:
"Hidden notes may paraphrase the same directive" (qa/public_sample_cases.json
_meta.how_to_use) - hard-coded phrase matching passes every public case and
still scores zero on paraphrased ones.

These notes reuse each public sample's numeric scenario (hours/battery) but
reword every operator note with different vocabulary and sentence structure,
so a real interpreter must still land on the same ground truth.

Needs network access to the deployed service. Skips automatically if the
service is unreachable so the rest of the suite is unaffected.
"""
import json
import pathlib

import pytest
import requests

URL = "https://gridwise.mashrurrahman.com"
ENDPOINT = URL.rstrip("/") + "/optimize-energy"
TOL = 0.01

CASES = {
    c["id"]: c
    for c in json.loads(
        (pathlib.Path(__file__).parent.parent / "qa" / "public_sample_cases.json")
        .read_text(encoding="utf-8")
    )["cases"]
}


def _scenario(case_id, paraphrased_notes):
    case = CASES[case_id]
    inp = json.loads(json.dumps(case["input"]))
    inp["operator_notes"] = paraphrased_notes
    return inp


# (case_id, paraphrased notes, expected directive_interpretation per note_index)
PARAPHRASES = [
    (
        "SAMPLE-01",
        [
            "Rooftop panel washing happens between 12:00 and 14:00; only about a "
            "quarter of the forecast solar yield will actually be usable then.",
            "Registration deadlines for next month were pushed back by the sports office.",
        ],
        [
            {"directive_type": "solar_reduction", "hours": [12, 13], "factor": 0.25},
            {"directive_type": "no_op"},
        ],
    ),
    (
        "SAMPLE-02",
        ["Electricians are pulling the charger offline between 02:00 and 05:00 "
         "for maintenance, so charging isn't possible then."],
        [{"directive_type": "no_charge_window", "hours": [2, 3, 4]}],
    ),
    (
        "SAMPLE-03",
        ["For emergency readiness, the battery should never drop under half its "
         "rated capacity between 18:00 and 21:00."],
        [{"directive_type": "minimum_battery_reserve", "hours": [18, 19, 20],
          "minimum_energy_kwh": 100}],
    ),
    (
        "SAMPLE-04",
        ["Technicians are running a protection test, so discharging the battery "
         "is off-limits from 6 to 8 in the evening."],
        [{"directive_type": "no_discharge_window", "hours": [18, 19]}],
    ),
    (
        "SAMPLE-05",
        ["The feeder is temporarily capped, so grid draw can't go over 155 kWh "
         "in any single hour between 18:00 and 21:00."],
        [{"directive_type": "max_grid_window", "hours": [18, 19, 20], "max_grid_kwh": 155}],
    ),
    (
        "SAMPLE-09",
        [
            "Inverter maintenance between 11:00 and 14:00 will cut rooftop solar "
            "output down to just one-fifth of what was forecast.",
            "Club notices will go out from the student affairs office tomorrow.",
        ],
        [
            {"directive_type": "solar_reduction", "hours": [11, 12, 13], "factor": 0.2},
            {"directive_type": "no_op"},
        ],
    ),
]


def _reachable():
    try:
        r = requests.get(URL.rstrip("/") + "/health", timeout=15)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(), reason="deployed service is unreachable"
)


@pytest.mark.parametrize(
    "case_id,notes,expected", PARAPHRASES, ids=[p[0] for p in PARAPHRASES]
)
def test_paraphrased_note_matches_ground_truth(case_id, notes, expected):
    """A reworded note must still produce the same directive as the original.

    Catches interpreters that hard-code the exact public-sample phrasing
    instead of actually reading the note (the failure mode the organizer's
    hidden, paraphrased cases are specifically designed to expose).
    """
    scenario = _scenario(case_id, notes)
    r = requests.post(ENDPOINT, json=scenario, timeout=35)
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
    body = r.json()

    got = body.get("directive_interpretation")
    assert isinstance(got, list) and len(got) == len(expected), (
        f"expected {len(expected)} entries, got {got}"
    )

    for i, (entry, exp) in enumerate(zip(got, expected)):
        assert entry.get("note_index") == i
        assert entry.get("directive_type") == exp["directive_type"], (
            f"note {i}: got {entry.get('directive_type')!r}, "
            f"want {exp['directive_type']!r} -- paraphrase not recognised"
        )
        if exp["directive_type"] == "no_op":
            assert entry.get("applies") is False
            assert entry.get("structured_adjustment") is None
            continue

        assert entry.get("applies") is True
        adj = entry.get("structured_adjustment")
        assert isinstance(adj, dict)
        assert adj.get("hours") == exp["hours"], (
            f"note {i}: hours {adj.get('hours')} != expected {exp['hours']} "
            "-- check start-inclusive/end-exclusive window handling"
        )
        for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
            if key in exp:
                val = adj.get(key)
                assert val is not None and abs(val - exp[key]) <= TOL, (
                    f"note {i}: {key} {val!r} != expected {exp[key]!r}"
                )


def test_paraphrased_multi_note_scenario_end_to_end():
    """Two independently reworded directives in one request, plus a distractor,
    replayed against ground truth the same way validate.py does (§7 of
    context.md) rather than just re-checking the interpretation JSON.
    """
    case = CASES["SAMPLE-06"]
    scenario = json.loads(json.dumps(case["input"]))
    scenario["operator_notes"] = [
        "Panel inspection with cloud cover means only roughly half the forecast "
        "solar will be available from 10:00 to noon.",
        "The charging line goes down for repairs between 14:00 and 16:00.",
        "Book-return hours at the library are being extended next week.",
    ]

    r = requests.post(ENDPOINT, json=scenario, timeout=35)
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
    body = r.json()

    interp = body.get("directive_interpretation")
    assert isinstance(interp, list) and len(interp) == 3
    assert interp[0]["directive_type"] == "solar_reduction"
    assert interp[0]["structured_adjustment"]["hours"] == [10, 11]
    assert abs(interp[0]["structured_adjustment"]["factor"] - 0.5) <= TOL
    assert interp[1]["directive_type"] == "no_charge_window"
    assert interp[1]["structured_adjustment"]["hours"] == [14, 15]
    assert interp[2]["directive_type"] == "no_op"

    plan = body.get("hourly_plan")
    assert isinstance(plan, list) and len(plan) == 24
    by_hour = {p["hour"]: p for p in plan}
    for h in (10, 11):
        eff_solar = case["input"]["hours"][h]["solar_kwh"] * 0.5
        assert by_hour[h]["solar_used_kwh"] <= eff_solar + TOL, (
            f"hour {h}: solar_used {by_hour[h]['solar_used_kwh']} exceeds "
            f"reduced effective solar {eff_solar}"
        )
    for h in (14, 15):
        assert by_hour[h]["battery_action"] != "charge", (
            f"hour {h}: charged during a no_charge_window derived from a "
            "paraphrased note"
        )
