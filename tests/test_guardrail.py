"""Hostile model output. Nothing here may crash, and nothing invalid may slip through."""
import json

import pytest

from app.guardrail import GuardrailError, parse_model_output, validate
from app.repair import repair

CAPACITY = 220.0
BASE = {"note_index": 0, "applies": True, "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12, 13], "factor": 0.25}, "explanation": "x"}
TRUTH = {"hours": [12, 13], "factor": 0.25}


def one(**kw):
    e = json.loads(json.dumps(BASE))
    e.update(kw)
    return json.dumps([e])


def strict(raw):
    return validate(parse_model_output(raw), 1, CAPACITY)


def lenient(raw):
    return validate(repair(parse_model_output(raw)), 1, CAPACITY)


ACCEPT = [
    ("clean output", one()),
    ("markdown fenced", "```json\n" + one() + "\n```"),
    ("prose around array", "Sure! Here you go:\n" + one() + "\nHope that helps."),
    ("hours unsorted", one(structured_adjustment={"hours": [13, 12], "factor": 0.25})),
    ("factor 0", one(structured_adjustment={"hours": [12], "factor": 0})),
    ("factor 1", one(structured_adjustment={"hours": [12], "factor": 1})),
    ("reserve equals capacity", one(directive_type="minimum_battery_reserve",
        structured_adjustment={"hours": [18], "minimum_energy_kwh": 220})),
    ("grid cap zero", one(directive_type="max_grid_window",
        structured_adjustment={"hours": [18], "max_grid_kwh": 0})),
    ("explanation omitted",
     '[{"note_index":0,"applies":true,"directive_type":"no_charge_window",'
     '"structured_adjustment":{"hours":[2,3]}}]'),
]

REJECT = [
    ("pure prose", "The note means solar drops to 25 percent."),
    ("empty string", ""),
    ("object not array", json.dumps(BASE)),
    ("null", "null"),
    ("empty array", "[]"),
    ("two entries for one note", "[" + json.dumps(BASE) + "," + json.dumps(BASE) + "]"),
    ("note_index out of range", one(note_index=5)),
    ("note_index negative", one(note_index=-1)),
    ("invented directive type", one(directive_type="reduce_demand")),
    ("directive_type null", one(directive_type=None)),
    ("no_op with applies true", one(directive_type="no_op", structured_adjustment=None)),
    ("no_op with adjustment", one(directive_type="no_op", applies=False)),
    ("real directive applies false", one(applies=False)),
    ("hours duplicated", one(structured_adjustment={"hours": [12, 12, 13], "factor": 0.25})),
    ("hour 24", one(structured_adjustment={"hours": [24], "factor": 0.25})),
    ("hour -1", one(structured_adjustment={"hours": [-1], "factor": 0.25})),
    ("hours empty", one(structured_adjustment={"hours": [], "factor": 0.25})),
    ("hours not a list", one(structured_adjustment={"hours": 12, "factor": 0.25})),
    ("factor above one", one(structured_adjustment={"hours": [12], "factor": 1.5})),
    ("factor negative", one(structured_adjustment={"hours": [12], "factor": -0.1})),
    ("factor missing", one(structured_adjustment={"hours": [12]})),
    ("extra key in adjustment",
     one(structured_adjustment={"hours": [12], "factor": 0.25, "zz": 1})),
    ("reserve above capacity", one(directive_type="minimum_battery_reserve",
        structured_adjustment={"hours": [18], "minimum_energy_kwh": 9999})),
    ("reserve negative", one(directive_type="minimum_battery_reserve",
        structured_adjustment={"hours": [18], "minimum_energy_kwh": -5})),
    ("grid cap negative", one(directive_type="max_grid_window",
        structured_adjustment={"hours": [18], "max_grid_kwh": -1})),
    ("wrong keys for type", one(directive_type="no_charge_window",
        structured_adjustment={"hours": [2], "factor": 0.5})),
    ("missing note_index key",
     '[{"applies":true,"directive_type":"no_op","structured_adjustment":null}]'),
    ("entry is a string", '["solar_reduction"]'),
    ("entry is null", "[null]"),
]


@pytest.mark.parametrize("name,raw", ACCEPT, ids=[n for n, _ in ACCEPT])
def test_accepts_valid_output(name, raw):
    assert len(strict(raw)) == 1


@pytest.mark.parametrize("name,raw", REJECT, ids=[n for n, _ in REJECT])
def test_rejects_invalid_output(name, raw):
    with pytest.raises(GuardrailError):
        strict(raw)


# --------------------------------------------------------------- repair behaviour

RESCUE = [
    ("duplicate hours", one(structured_adjustment={"hours": [12, 12, 13], "factor": 0.25})),
    ("hours as strings", one(structured_adjustment={"hours": ["12", "13"], "factor": 0.25})),
    ("hours as floats", one(structured_adjustment={"hours": [12.0, 13.0], "factor": 0.25})),
    ("hours unsorted", one(structured_adjustment={"hours": [13, 12], "factor": 0.25})),
    ("factor as string", one(structured_adjustment={"hours": [12, 13], "factor": "0.25"})),
    ("factor as percent string", one(structured_adjustment={"hours": [12, 13], "factor": "25%"})),
    ("junk key present",
     one(structured_adjustment={"hours": [12, 13], "factor": 0.25, "zz": 9})),
    ("applies as string", one(applies="true")),
    ("note_index as string", one(note_index="0")),
    ("type in capitals", one(directive_type="SOLAR_REDUCTION")),
    ("complete directive marked not applying", one(applies=False)),
]


@pytest.mark.parametrize("name,raw", RESCUE, ids=[n for n, _ in RESCUE])
def test_repair_recovers_unambiguous_slips(name, raw):
    """Each of these has exactly one sane reading, so rejecting them would lose a
    note AND leave its constraint unapplied."""
    out = lenient(raw)
    assert out[0]["directive_type"] == "solar_reduction"
    assert out[0]["structured_adjustment"] == TRUTH, f"{name} landed on the wrong value"


NO_LEAK = [
    ("factor 1.5 stays ambiguous", one(structured_adjustment={"hours": [12], "factor": 1.5})),
    ("bare 25 stays ambiguous", one(structured_adjustment={"hours": [12], "factor": 25})),
    ("invented type", one(directive_type="reduce_demand")),
    ("hour 24", one(structured_adjustment={"hours": [24], "factor": 0.25})),
    ("reserve above capacity", one(directive_type="minimum_battery_reserve",
        structured_adjustment={"hours": [18], "minimum_energy_kwh": 9999})),
    ("wrong entry count", "[" + json.dumps(BASE) + "," + json.dumps(BASE) + "]"),
    ("pure prose", "no json here at all"),
    ("hours empty", one(structured_adjustment={"hours": [], "factor": 0.25})),
    ("factor missing", one(structured_adjustment={"hours": [12]})),
]


@pytest.mark.parametrize("name,raw", NO_LEAK, ids=[n for n, _ in NO_LEAK])
def test_repair_does_not_weaken_hard_rejects(name, raw):
    """Repair must never turn a genuinely ambiguous or invalid output into an accept."""
    with pytest.raises(GuardrailError):
        lenient(raw)


def test_no_op_pairing_is_normalised():
    out = lenient(one(directive_type="no_op"))
    assert out[0]["applies"] is False
    assert out[0]["structured_adjustment"] is None


def test_entries_are_returned_in_note_index_order():
    entries = json.dumps([
        {"note_index": 2, "applies": False, "directive_type": "no_op",
         "structured_adjustment": None, "explanation": ""},
        {"note_index": 0, "applies": True, "directive_type": "no_charge_window",
         "structured_adjustment": {"hours": [2, 3]}, "explanation": ""},
        {"note_index": 1, "applies": False, "directive_type": "no_op",
         "structured_adjustment": None, "explanation": ""},
    ])
    out = validate(repair(parse_model_output(entries)), 3, CAPACITY)
    assert [e["note_index"] for e in out] == [0, 1, 2]
