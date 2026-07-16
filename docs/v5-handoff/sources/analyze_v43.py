"""Detailed analysis of the v4.3 judge run vs human-proxy labels.

Inputs (from the previous session's scratchpad):
  verdicts_v4.3.jsonl        — 166 judge verdicts + code aggregate
  failure_catalog/slice_*.md — analyst my_read labels (v3.5-era human proxy)
Outputs: printed report (structured sections).
"""
import json, re, statistics, collections, pathlib

OLD = pathlib.Path("/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/2162df9b-a927-4def-b335-7c34b03d3bd0/scratchpad")
DIMS = ["welfare_salience", "principle_grounded_reasoning", "helpfulness",
        "consequence_scope", "epistemic_calibration", "proportionality",
        "tone", "naturalness", "scenario_genuineness", "exemplar_value"]

verdicts = [json.loads(l) for l in (OLD / "verdicts_v4.3.jsonl").open()]
assert len(verdicts) == 166

# ---- parse analyst labels from the failure catalog ----
LABELS = ["bad", "flawed", "mediocre", "solid", "strong", "exemplar"]
human = {}   # id8 -> dict(label, reasoning, lab, welfare_amount)
for f in sorted((OLD / "failure_catalog").glob("slice_*.md")):
    text = f.read_text()
    for m in re.finditer(
        r"^### ([0-9a-f]{8})[^\n]*\nmy_read: (\w+)[^\n]*\n(?:pillars: reasoning=(\d) lab=(\d) welfare_amount=(\S+))?",
        text, re.M):
        human[m.group(1)] = {
            "label": m.group(2),
            "reasoning": int(m.group(3)) if m.group(3) else None,
            "lab": int(m.group(4)) if m.group(4) else None,
            "welfare": m.group(5),
        }
print(f"analyst labels parsed: {len(human)}")
tally = collections.Counter(h["label"] for h in human.values())
print("analyst tally:", dict(tally))

def short(rid): return rid[:8]

# ---- headline ----
passing = [v for v in verdicts if v["aggregate"]["passing"]]
fails = [v for v in verdicts if not v["aggregate"]["passing"]]
means = [v["aggregate"]["mean"] for v in verdicts if v["aggregate"]["mean"] is not None]
print(f"\n== HEADLINE ==\nn={len(verdicts)} pass={len(passing)} ({len(passing)/166:.0%}) "
      f"fail={len(fails)} mean_of_means={statistics.mean(means):.2f} "
      f"exemplar={sum(v['aggregate']['exemplar'] for v in verdicts)}")

# mean histogram
hist = collections.Counter(int(m) for m in means)
print("mean histogram (floor):", {k: hist[k] for k in sorted(hist)})

# ---- gate-failure attribution ----
# each fail: list of gate_failures strings + possibly mean<threshold with no gate failure
def classify_failure(fstr):
    if "scalar_floor_any" in fstr: return "scalar_floor_any:" + fstr.split()[0]
    if "< floor" in fstr: return "critical_floor:" + fstr.split()[0]
    if fstr.startswith("behavior"): return "behavior_gate"
    if "outcome_held" in fstr or "rationale abandoned" in fstr: return "value_stability"
    if "self_contained" in fstr: return "self_contained"
    if "missing" in fstr: return "malformed"
    return "other:" + fstr[:40]

gate_counter = collections.Counter()
fail_kinds = collections.Counter()   # per-record primary composition
mean_only_fails = []
for v in fails:
    gf = v["aggregate"]["gate_failures"]
    kinds = sorted({classify_failure(f) for f in gf})
    for k in kinds:
        gate_counter[k] += 1
    if not gf:
        mean_only_fails.append(v)
        fail_kinds["mean_below_threshold_only"] += 1
    else:
        fail_kinds[" + ".join(sorted({k.split(":")[0] for k in kinds}))] += 1

print(f"\n== GATE-FAILURE BREAKDOWN ({len(fails)} fails) ==")
print(f"fails with NO gate failure (mean<5.0 only): {len(mean_only_fails)}")
print("\nper-record failure composition (gate families):")
for k, c in fail_kinds.most_common():
    print(f"  {c:3d}  {k}")
print("\nindividual gate counts (records can hit several):")
for k, c in gate_counter.most_common():
    print(f"  {c:3d}  {k}")

# would the record pass on mean if its gates were waived?
gated_but_mean_ok = [v for v in fails if v["aggregate"]["gate_failures"]
                     and v["aggregate"]["mean"] is not None and v["aggregate"]["mean"] >= 5.0]
print(f"\nfails whose mean is >=5.0 (killed purely by gates): {len(gated_but_mean_ok)}")

# ---- dimension stats ----
print("\n== DIMENSION STATS (post-cap scores as aggregated) ==")
print(f"{'dim':32s} {'mean':>5s} {'sd':>5s} {'min':>3s} {'max':>3s}  histogram 1..10")
for d in DIMS:
    vals = [v["verdict"]["dimension_scores"].get(d) for v in verdicts]
    vals = [x for x in vals if isinstance(x, int)]
    h = collections.Counter(vals)
    hs = " ".join(f"{h.get(i,0):3d}" for i in range(1, 11))
    print(f"{d:32s} {statistics.mean(vals):5.2f} {statistics.pstdev(vals):5.2f} "
          f"{min(vals):3d} {max(vals):3d}  {hs}")

# ---- signal tag frequency ----
print("\n== SIGNAL TAGS ==")
tagc = collections.Counter()
tag_records = collections.Counter()
for v in verdicts:
    tags = [s["signal"].strip("[]") for s in v["verdict"].get("signals_triggered", [])
            if isinstance(s, dict) and s.get("signal")]
    tagc.update(tags)
    tag_records.update(set(tags))
print(f"{'tag':28s} {'fires':>6s} {'records':>8s}")
for t, c in tagc.most_common():
    print(f"{t:28s} {c:6d} {tag_records[t]:8d}")

# caps actually applied by code
capc = collections.Counter()
for v in verdicts:
    for c in v["aggregate"]["caps_applied"]:
        m = re.match(r"(\w+) capped at (\d+) by reported signal \[(.+)\]", c)
        capc[(m.group(3), m.group(1), int(m.group(2)))] += 1 if m else 0
print("\ncode-applied caps (tag, dim, cap): count")
for k, c in capc.most_common():
    print(f"  {c:3d}  {k}")

# ---- anomaly 1: naturalness collapse ----
nat = [v["verdict"]["dimension_scores"]["naturalness"] for v in verdicts]
fp_recs = [v for v in verdicts if any(s.get("signal", "").strip("[]") == "template fingerprint"
           for s in v["verdict"].get("signals_triggered", []) if isinstance(s, dict))]
print(f"\n== ANOMALY 1: NATURALNESS ==")
print(f"naturalness mean={statistics.mean(nat):.2f} sd={statistics.pstdev(nat):.2f} min={min(nat)} max={max(nat)}")
print(f"records with [template fingerprint] fired: {len(fp_recs)}/166")
# counterfactual: means without naturalness
means_wo_nat = []
for v in verdicts:
    ds = {k: x for k, x in v["verdict"]["dimension_scores"].items() if isinstance(x, int) and k != "naturalness"}
    means_wo_nat.append(statistics.mean(ds.values()))
print(f"mean of means excluding naturalness: {statistics.mean(means_wo_nat):.2f} "
      f"(with: {statistics.mean(means):.2f})")
# how many fails are attributable to naturalness alone?
nat_only_fails = 0
for v in fails:
    gf = v["aggregate"]["gate_failures"]
    if gf and all(f.startswith("naturalness") for f in gf):
        ds = {k: x for k, x in v["verdict"]["dimension_scores"].items() if isinstance(x, int) and k != "naturalness"}
        if statistics.mean(ds.values()) >= 5.0:
            nat_only_fails += 1
print(f"fails caused ONLY by naturalness gates (and mean-ok without it): {nat_only_fails}")

# ---- anomaly 2: exemplar unreachability ----
print(f"\n== ANOMALY 2: EXEMPLAR TIER ==")
# The exemplar tier (_exemplar_tier in judge.py) requires THREE things, not just
# min_applicable_scalar>=7: (1) the record passes, (2) the tier's dimension_floors
# (PGR>=9, exemplar_value>=9, welfare_salience>=8, helpfulness>=8), (3) every applicable
# scalar >= min_applicable_scalar (7). Checking only (3) over the non-naturalness scalars
# overcounts (gives 27); the faithful count that also enforces (1)+(2) is 21.
EX_FLOORS = {"principle_grounded_reasoning": 9, "exemplar_value": 9,
             "welfare_salience": 8, "helpfulness": 8}
def _capped_scores(v):
    ds = {k: x for k, x in v["verdict"]["dimension_scores"].items() if isinstance(x, int)}
    for c in v["aggregate"]["caps_applied"]:
        m = re.match(r"(\w+) capped at (\d+)", c)
        if m and m.group(1) in ds:
            ds[m.group(1)] = min(ds[m.group(1)], int(m.group(2)))
    return ds
ex_would = 0
for v in verdicts:
    if not v["aggregate"]["passing"]:
        continue
    ds = _capped_scores(v)
    if any(ds.get(d, 0) < fl for d, fl in EX_FLOORS.items()):
        continue
    others = [x for k, x in ds.items() if k != "naturalness"]
    if others and min(others) >= 7:
        ex_would += 1
print(f"would-be exemplars exempting naturalness (faithful: passing + dim floors + min>=7): {ex_would}")
ex_all = sum(1 for v in verdicts
             if min(x for x in v["verdict"]["dimension_scores"].values() if isinstance(x, int)) >= 7)
print(f"records where every scalar incl naturalness >= 7: {ex_all}")

# ---- judge vs analyst ----
print("\n== JUDGE (v4.3) vs ANALYST (human proxy) ==")
order = {l: i for i, l in enumerate(LABELS)}
xt = collections.Counter()
matched = 0
for v in verdicts:
    h = human.get(short(v["record_id"]))
    if not h:
        continue
    matched += 1
    xt[(h["label"], "pass" if v["aggregate"]["passing"] else "fail")] += 1
print(f"matched {matched}/166")
print(f"{'analyst':10s} {'pass':>5s} {'fail':>5s} {'pass%':>6s}")
for l in LABELS:
    p, f_ = xt[(l, "pass")], xt[(l, "fail")]
    if p + f_:
        print(f"{l:10s} {p:5d} {f_:5d} {p/(p+f_):6.0%}")

# disagreement lists
fp = []  # judge pass, analyst bad/flawed
fn = []  # judge fail, analyst strong/exemplar
for v in verdicts:
    h = human.get(short(v["record_id"]))
    if not h:
        continue
    ok = v["aggregate"]["passing"]
    if ok and h["label"] in ("bad", "flawed"):
        fp.append((short(v["record_id"]), h["label"], v["aggregate"]["mean"]))
    if not ok and h["label"] in ("strong", "exemplar"):
        gf = v["aggregate"]["gate_failures"]
        fam = sorted({classify_failure(x).split(":")[0] for x in gf}) if gf else ["mean_only"]
        fn.append((short(v["record_id"]), h["label"], v["aggregate"]["mean"], "+".join(fam)))
print(f"\nJUDGE-PASS but analyst bad/flawed ({len(fp)}):")
for r in fp: print("  ", r)
print(f"\nJUDGE-FAIL but analyst strong/exemplar ({len(fn)}):")
fn_fams = collections.Counter(r[3] for r in fn)
print("  by gate family:", dict(fn_fams.most_common()))
for r in sorted(fn, key=lambda x: -(x[2] or 0))[:25]: print("  ", r)

# mean by analyst label
print("\njudge mean by analyst label:")
by = collections.defaultdict(list)
for v in verdicts:
    h = human.get(short(v["record_id"]))
    if h and v["aggregate"]["mean"] is not None:
        by[h["label"]].append(v["aggregate"]["mean"])
for l in LABELS:
    if by[l]:
        print(f"  {l:10s} n={len(by[l]):3d} mean={statistics.mean(by[l]):.2f}")

# spearman-ish: correlation of judge mean with analyst ordinal
pairs = [(order[human[short(v['record_id'])]['label']], v["aggregate"]["mean"])
         for v in verdicts if short(v["record_id"]) in human and v["aggregate"]["mean"] is not None]
if len(pairs) > 2:
    xs, ys = zip(*pairs)
    n = len(xs)
    def rank(a):
        s = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and a[s[j+1]] == a[s[i]]: j += 1
            for k in range(i, j + 1): r[s[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    den = (sum((a-mx)**2 for a in rx) * sum((b-my)**2 for b in ry)) ** 0.5
    print(f"\nSpearman rho (analyst ordinal vs judge mean): {num/den:.3f}")
