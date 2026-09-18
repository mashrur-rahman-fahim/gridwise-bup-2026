"""Full response-contract audit, written from the judge's point of view.

Every check is derived from the organizers' own required-field lists in the sample
cases metadata rather than from a hand-written list. That matters: an earlier
hand-rolled check validated directive types, hours and numeric values but never
looked at `explanation`, so entries shipped with that field blank and nothing
noticed. Deriving the field set from the contract means a field nobody thought
about still gets validated.

Used by tests, and by the service itself as a final self-check before responding.
"""
import json, math, urllib.request, urllib.error

import pathlib
_SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "samples" / "public_sample_cases.json"
META = json.loads(_SAMPLES.read_text())["_meta"]
REQ_TOP   = META["schema_notes"]["output_required_fields"]
REQ_DI    = META["schema_notes"]["directive_interpretation_required_fields"]
REQ_HP    = META["schema_notes"]["hourly_plan_required_fields"]
DTYPES    = set(META["allowed_enums"]["directive_type"])
ACTIONS   = set(META["allowed_enums"]["battery_action"])
ADJ_KEYS  = {"solar_reduction":{"hours","factor"},
             "minimum_battery_reserve":{"hours","minimum_energy_kwh"},
             "no_charge_window":{"hours"}, "no_discharge_window":{"hours"},
             "max_grid_window":{"hours","max_grid_kwh"}}
TOL = 0.01

def num(v): return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def audit(request, response):
    """Return a list of contract violations. Empty means the response is fully valid."""
    E=[]
    notes=request["operator_notes"]; batt=request["battery"]
    H={h["hour"]:h for h in request["hours"]}

    # ---------- top level ----------
    for f in REQ_TOP:
        if f not in response: E.append(f"top-level: missing '{f}'")
    for f in response:
        if f not in REQ_TOP: E.append(f"top-level: unexpected field '{f}'")
    if response.get("scenario_id") != request["scenario_id"]:
        E.append("scenario_id not echoed exactly")
    if not isinstance(response.get("plan_summary"), str) or not response["plan_summary"].strip():
        E.append("plan_summary must be a non-empty string")
    for f in ("total_grid_kwh","total_cost_bdt","peak_grid_kwh"):
        if f in response and not num(response[f]): E.append(f"{f} is not a finite number")
        elif f in response and response[f] < -TOL: E.append(f"{f} is negative")

    # ---------- directive_interpretation ----------
    di = response.get("directive_interpretation")
    if not isinstance(di, list):
        E.append("directive_interpretation is not an array"); return E
    if len(di) != len(notes):
        E.append(f"directive_interpretation has {len(di)} entries for {len(notes)} notes")
    idx=[]
    for i,e in enumerate(di):
        p=f"directive_interpretation[{i}]"
        if not isinstance(e,dict): E.append(f"{p}: not an object"); continue
        for f in REQ_DI:
            if f not in e: E.append(f"{p}: missing '{f}'")
        for f in e:
            if f not in REQ_DI: E.append(f"{p}: unexpected field '{f}'")
        ni=e.get("note_index")
        if isinstance(ni,bool) or not isinstance(ni,int): E.append(f"{p}: note_index not an int")
        else:
            idx.append(ni)
            if not 0 <= ni < len(notes): E.append(f"{p}: note_index {ni} out of range")
        if not isinstance(e.get("applies"), bool): E.append(f"{p}: applies not a bool")
        t=e.get("directive_type")
        if t not in DTYPES: E.append(f"{p}: directive_type {t!r} not allowed")
        # THE FIELD THAT WAS SILENTLY EMPTY
        ex=e.get("explanation")
        if not isinstance(ex,str): E.append(f"{p}: explanation is not a string")
        elif not ex.strip(): E.append(f"{p}: explanation is EMPTY (spec requires a short explanation)")
        a=e.get("structured_adjustment")
        if t=="no_op":
            if e.get("applies") is not False: E.append(f"{p}: no_op must have applies=false")
            if a is not None: E.append(f"{p}: no_op must have null structured_adjustment")
        else:
            if e.get("applies") is not True: E.append(f"{p}: {t} must have applies=true")
            if not isinstance(a,dict): E.append(f"{p}: {t} needs a structured_adjustment object")
            else:
                if set(a)!=ADJ_KEYS.get(t,set()):
                    E.append(f"{p}: {t} keys {sorted(a)} != {sorted(ADJ_KEYS.get(t,()))}")
                hrs=a.get("hours")
                if not isinstance(hrs,list) or not hrs: E.append(f"{p}: hours must be a non-empty list")
                else:
                    if any(isinstance(h,bool) or not isinstance(h,int) for h in hrs):
                        E.append(f"{p}: hours must all be integers")
                    elif hrs!=sorted(set(hrs)): E.append(f"{p}: hours not unique+ascending: {hrs}")
                    elif not all(0<=h<=23 for h in hrs): E.append(f"{p}: hours outside 0..23")
                if t=="solar_reduction":
                    f_=a.get("factor")
                    if not num(f_): E.append(f"{p}: factor not finite")
                    elif not 0.0<=f_<=1.0: E.append(f"{p}: factor {f_} outside [0,1]")
                if t=="minimum_battery_reserve":
                    r=a.get("minimum_energy_kwh")
                    if not num(r): E.append(f"{p}: reserve not finite")
                    elif r<0 or r>batt["capacity_kwh"]: E.append(f"{p}: reserve {r} outside [0,capacity]")
                if t=="max_grid_window":
                    g=a.get("max_grid_kwh")
                    if not num(g): E.append(f"{p}: max_grid_kwh not finite")
                    elif g<0: E.append(f"{p}: max_grid_kwh negative")
    if idx and idx!=sorted(idx): E.append(f"entries not in note_index order: {idx}")
    if len(set(idx))!=len(idx): E.append("duplicate note_index values")

    # ---------- rebuild effective constraints from the RETURNED interpretation ----------
    eff={h:float(H[h]["solar_kwh"]) for h in range(24)}
    nochg=set(); nodis=set(); res={}; cap={}
    for e in di:
        a=e.get("structured_adjustment"); t=e.get("directive_type")
        if t=="no_op" or not isinstance(a,dict): continue
        for h in a.get("hours",[]):
            if not isinstance(h,int) or not 0<=h<=23: continue
            if t=="solar_reduction": eff[h]=min(eff[h], float(H[h]["solar_kwh"])*a["factor"])
            elif t=="no_charge_window": nochg.add(h)
            elif t=="no_discharge_window": nodis.add(h)
            elif t=="minimum_battery_reserve": res[h]=max(res.get(h,0.0), a["minimum_energy_kwh"])
            elif t=="max_grid_window": cap[h]=min(cap.get(h,float("inf")), a["max_grid_kwh"])

    # ---------- hourly_plan ----------
    hp=response.get("hourly_plan")
    if not isinstance(hp,list): E.append("hourly_plan is not an array"); return E
    if len(hp)!=24: E.append(f"hourly_plan has {len(hp)} rows, expected 24")
    for i,r in enumerate(hp):
        if not isinstance(r,dict): E.append(f"hourly_plan[{i}]: not an object"); continue
        for f in REQ_HP:
            if f not in r: E.append(f"hourly_plan[{i}]: missing '{f}'")
        for f in r:
            if f not in REQ_HP: E.append(f"hourly_plan[{i}]: unexpected field '{f}'")
    hours=[r.get("hour") for r in hp]
    if sorted(x for x in hours if isinstance(x,int))!=list(range(24)):
        E.append("hourly_plan hours are not exactly 0..23 once each")

    energy=float(batt["initial_energy_kwh"]); tg=tc=pk=0.0
    for r in sorted([x for x in hp if isinstance(x.get("hour"),int)], key=lambda x:x["hour"]):
        h=r["hour"]; p=f"hour {h}"
        g,s,k,act = r.get("grid_kwh"), r.get("solar_used_kwh"), r.get("battery_kwh"), r.get("battery_action")
        if not num(g) or g<-TOL: E.append(f"{p}: grid_kwh invalid/negative")
        if not num(s) or s<-TOL: E.append(f"{p}: solar_used_kwh invalid/negative")
        if not num(k) or k<-TOL: E.append(f"{p}: battery_kwh invalid/negative")
        if act not in ACTIONS: E.append(f"{p}: battery_action {act!r} not allowed"); continue
        if act=="idle" and abs(k)>TOL: E.append(f"{p}: idle with battery_kwh {k}")
        chg=k if act=="charge" else 0.0; dis=k if act=="discharge" else 0.0
        if s>eff[h]+TOL: E.append(f"{p}: solar_used {s} exceeds effective solar {eff[h]:.4f}")
        if abs(g+s+dis-(H[h]["demand_kwh"]+chg))>TOL: E.append(f"{p}: energy balance violated")
        energy+=chg-dis
        if not num(r.get("battery_energy_after_kwh")): E.append(f"{p}: battery_energy_after_kwh invalid")
        elif abs(energy-r["battery_energy_after_kwh"])>TOL: E.append(f"{p}: battery_energy_after_kwh inconsistent")
        floor=max(batt["minimum_energy_kwh"], res.get(h,0.0))
        if energy<floor-TOL or energy>batt["capacity_kwh"]+TOL:
            E.append(f"{p}: battery {energy:.3f} outside [{floor},{batt['capacity_kwh']}]")
        if chg>batt["max_charge_kwh_per_hour"]+TOL: E.append(f"{p}: charge rate exceeded")
        if dis>batt["max_discharge_kwh_per_hour"]+TOL: E.append(f"{p}: discharge rate exceeded")
        if h in nochg and chg>TOL: E.append(f"{p}: charged inside no_charge_window")
        if h in nodis and dis>TOL: E.append(f"{p}: discharged inside no_discharge_window")
        if h in cap and g>cap[h]+TOL: E.append(f"{p}: grid {g} exceeds cap {cap[h]}")
        tg+=g; tc+=g*H[h]["tariff_bdt_per_kwh"]; pk=max(pk,g)

    if abs(energy-batt["initial_energy_kwh"])>TOL:
        E.append(f"end-of-day battery {energy:.3f} != initial {batt['initial_energy_kwh']}")
    if "total_grid_kwh" in response and abs(tg-response["total_grid_kwh"])>TOL:
        E.append(f"total_grid_kwh {response['total_grid_kwh']} != recomputed {tg:.4f}")
    if "total_cost_bdt" in response and abs(tc-response["total_cost_bdt"])>TOL:
        E.append(f"total_cost_bdt {response['total_cost_bdt']} != recomputed {tc:.4f}")
    if "peak_grid_kwh" in response and abs(pk-response["peak_grid_kwh"])>TOL:
        E.append(f"peak_grid_kwh {response['peak_grid_kwh']} != recomputed {pk:.4f}")
    return E
