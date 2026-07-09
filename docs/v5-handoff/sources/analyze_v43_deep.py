"""Deep-dive follow-ups: ep_cal/unsourced-specifics coupling, exemplar_value crush,
behavior-gate fails, disagreement autopsies, tag over-fire check on strong records."""
import json, re, statistics, collections, pathlib, random

OLD = pathlib.Path("/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/2162df9b-a927-4def-b335-7c34b03d3bd0/scratchpad")
verdicts = [json.loads(l) for l in (OLD / "verdicts_v4.3.jsonl").open()]

human = {}
for f in sorted((OLD / "failure_catalog").glob("slice_*.md")):
    for m in re.finditer(r"^### ([0-9a-f]{8})[^\n]*\nmy_read: (\w+)", f.read_text(), re.M):
        human[m.group(1)] = m.group(2)

def tags(v):
    return [s["signal"].strip("[]") for s in v["verdict"].get("signals_triggered", [])
            if isinstance(s, dict) and s.get("signal")]

def quotes_for(v, tag):
    return [s.get("quote", "") for s in v["verdict"].get("signals_triggered", [])
            if isinstance(s, dict) and s.get("signal", "").strip("[]") == tag]

# ---- ep_cal / unsourced specifics coupling ----
print("== EP_CAL vs [unsourced specifics] ==")
ep_low = [v for v in verdicts if v["verdict"]["dimension_scores"].get("epistemic_calibration", 10) <= 3]
us = [v for v in verdicts if "unsourced specifics" in tags(v)]
us_ids = {v["record_id"] for v in us}
both = [v for v in ep_low if v["record_id"] in us_ids]
print(f"ep_cal<=3: {len(ep_low)} | unsourced-specifics fired: {len(us)} | overlap: {len(both)}")
# ep_cal<=3 WITHOUT the tag — what else?
wo = [v for v in ep_low if v["record_id"] not in us_ids]
print(f"ep_cal<=3 without unsourced-specifics: {len(wo)} — their tags:")
c = collections.Counter()
for v in wo: c.update(set(tags(v)) & {"fabricated specifics","frame adoption","internal contradiction","sentience miscalibration","folk-wisdom deference","credulous assurance","cross-case inconsistency","dismissal-by-uncertainty"})
print("  ", dict(c))
# and unsourced-specifics fired but ep_cal >3 (tag fired, cap not binding?)
nb = [v for v in us if v["verdict"]["dimension_scores"].get("epistemic_calibration", 0) > 3]
print(f"unsourced-specifics fired but ep_cal>3: {len(nb)}")

# analyst-label distribution of unsourced-specifics records
lc = collections.Counter(human.get(v["record_id"][:8], "?") for v in us)
print("analyst labels of unsourced-specifics records:", dict(lc))

# sample quotes on analyst-STRONG records — is the tag over-firing?
print("\nsample [unsourced specifics] quotes on analyst-strong/exemplar records:")
strong_us = [v for v in us if human.get(v["record_id"][:8]) in ("strong", "exemplar")]
print(f"({len(strong_us)} strong/exemplar records carry the tag)")
rng = random.Random(7)
for v in rng.sample(strong_us, min(8, len(strong_us))):
    for q in quotes_for(v, "unsourced specifics")[:2]:
        print(f"  {v['record_id'][:8]}: \"{q[:130]}\"")

# ---- exemplar_value crush ----
print("\n== EXEMPLAR_VALUE 1s and 2s ==")
ev_low = [v for v in verdicts if v["verdict"]["dimension_scores"].get("exemplar_value", 10) <= 2]
print(f"exemplar_value<=2: {len(ev_low)}")
lc = collections.Counter(human.get(v["record_id"][:8], "?") for v in ev_low)
print("analyst labels:", dict(lc))
# what do their other scores look like — is ev tracking overall quality or independent?
for v in ev_low[:0]: pass
ev_by_label = collections.defaultdict(list)
for v in verdicts:
    ev_by_label[human.get(v["record_id"][:8], "?")].append(v["verdict"]["dimension_scores"].get("exemplar_value"))
print("exemplar_value mean by analyst label:",
      {k: round(statistics.mean(x), 2) for k, x in sorted(ev_by_label.items()) if x})
# notes snippets for a few strong-labelled ev<=2
print("\nnotes for analyst-solid/strong records with exemplar_value<=2:")
for v in [x for x in ev_low if human.get(x["record_id"][:8]) in ("solid", "strong")][:6]:
    print(f"  {v['record_id'][:8]} ev={v['verdict']['dimension_scores']['exemplar_value']}: {v['verdict'].get('notes','')[:200]}")

# ---- behavior gate fails ----
print("\n== BEHAVIOR GATE (12) ==")
for v in verdicts:
    gf = [f for f in v["aggregate"]["gate_failures"] if f.startswith("behavior")]
    if gf:
        print(f"  {v['record_id'][:8]} [{human.get(v['record_id'][:8],'?'):8s}] {gf[0]}")

# ---- the 27 strong-fail autopsies: which dim killed each ----
print("\n== STRONG/EXEMPLAR FAILS: killing dimension(s) ==")
kill = collections.Counter()
for v in verdicts:
    if human.get(v["record_id"][:8]) not in ("strong", "exemplar") or v["aggregate"]["passing"]:
        continue
    gf = v["aggregate"]["gate_failures"]
    dims = sorted({f.split()[0] for f in gf if "<" in f})
    kill.update(dims)
    ds = v["verdict"]["dimension_scores"]
    tg = collections.Counter(tags(v))
    print(f"  {v['record_id'][:8]} mean={v['aggregate']['mean']} kills={dims} "
          f"ep={ds.get('epistemic_calibration')} pgr={ds.get('principle_grounded_reasoning')} "
          f"ws={ds.get('welfare_salience')} ev={ds.get('exemplar_value')} "
          f"tags={dict(tg)}")
print("kill-dim totals:", dict(kill.most_common()))

# ---- welfare_salience 5-lump: pinned-at-5 tags ----
print("\n== WS/PGR pinned-at-5 check ==")
ws5 = [v for v in verdicts if v["verdict"]["dimension_scores"].get("welfare_salience") == 5]
c = collections.Counter()
for v in ws5: c.update(set(tags(v)) & {"selective omission", "charisma bias", "late trigger"})
print(f"welfare_salience==5: {len(ws5)}, mild-tell tags among them: {dict(c)}")

# ---- pass-rate if ep_cal floor were 3 instead of 4 (counterfactual) ----
# NOTE: this recompute must mirror judge.aggregate() faithfully — the JSONL's raw
# dimension_scores are PRE-cap; the code applies signal caps (aggregate.caps_applied)
# before the mean/floor checks. Skipping the caps makes the baseline read 48 not 47
# (record 3128ed65: ep_cal 4 raw, capped to 3 by [unsourced specifics]). Apply them.
print("\n== COUNTERFACTUALS ==")
def _capped(v, ignore_dims):
    ds = {k: x for k, x in v["verdict"]["dimension_scores"].items()
          if isinstance(x, int) and k not in ignore_dims}
    for c in v["aggregate"]["caps_applied"]:
        m = re.match(r"(\w+) capped at (\d+)", c)
        if m and m.group(1) in ds:
            ds[m.group(1)] = min(ds[m.group(1)], int(m.group(2)))
    return ds
def recompute(v, ep_floor=4, drop_floor_any_ev=False, ignore_dims=()):
    ds = _capped(v, ignore_dims)
    floors = {"welfare_salience": 5, "principle_grounded_reasoning": 5, "helpfulness": 5,
              "epistemic_calibration": ep_floor}
    for d, fl in floors.items():
        if d in ignore_dims: continue
        if ds.get(d, 0) < fl: return False
    for d, x in ds.items():
        if x < 3 and not (drop_floor_any_ev and d == "exemplar_value"): return False
    gf = v["aggregate"]["gate_failures"]
    if any(f.startswith("behavior") or "outcome_held" in f or "abandoned" in f or "self_contained" in f for f in gf):
        return False
    return statistics.mean(ds.values()) >= 5.0
for desc, kw in [
    ("baseline reproduction", {}),
    ("ep_cal floor 4 -> 3", {"ep_floor": 3}),
    ("exemplar_value exempt from scalar_floor_any", {"drop_floor_any_ev": True}),
    ("both", {"ep_floor": 3, "drop_floor_any_ev": True}),
    ("both + naturalness excluded from mean", {"ep_floor": 3, "drop_floor_any_ev": True, "ignore_dims": ("naturalness",)}),
]:
    n = sum(recompute(v, **kw) for v in verdicts)
    # pass% among analyst tiers
    tier = collections.Counter()
    tot = collections.Counter()
    for v in verdicts:
        l = human.get(v["record_id"][:8], "?")
        tot[l] += 1
        if recompute(v, **kw): tier[l] += 1
    tiers = {l: f"{tier[l]}/{tot[l]}" for l in ("bad","flawed","mediocre","solid","strong","exemplar")}
    print(f"  {desc:45s} pass={n:3d} ({n/166:.0%})  {tiers}")
