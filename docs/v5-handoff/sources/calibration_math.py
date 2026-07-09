"""Calibration math for the v4.3 judge run — the quantitative basis for the
category-by-category rubric pruning.

Answers, per dimension:
  - variance / information content (a near-constant dim carries no signal)
  - redundancy: pairwise Spearman among the 10 scalars; merge candidates (|rho| high)
  - latent structure: PCA — how many factors actually drive the 10 scores
  - discrimination: Spearman + eta^2 vs the analyst ordinal (external ground truth)
  - INCREMENTAL value: OLS of analyst-ordinal on all dims (standardized betas) and
    drop-one Delta-R^2 — a dim that adds nothing beyond the others is a copy
  - mutual information dim -> analyst label
Plus:
  - gate co-occurrence + unique-kill counts (which gates are load-bearing vs redundant)
  - threshold calibration: current pass/fail vs analyst "usable" (solid+), precision/
    recall/F1/MCC, and a pure-mean threshold sweep.

Effective (code-capped) scores are used throughout, matching judge.aggregate().
numpy only; everything else hand-rolled.
"""
import json, re, statistics, collections, pathlib
import numpy as np

OLD = pathlib.Path("/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/2162df9b-a927-4def-b335-7c34b03d3bd0/scratchpad")
DIMS = ["welfare_salience","principle_grounded_reasoning","consequence_scope",
        "epistemic_calibration","proportionality","helpfulness","tone",
        "naturalness","scenario_genuineness","exemplar_value"]
AB = {"welfare_salience":"WS","principle_grounded_reasoning":"PGR","consequence_scope":"CSco",
      "epistemic_calibration":"EpCal","proportionality":"Prop","helpfulness":"Help",
      "tone":"Tone","naturalness":"Nat","scenario_genuineness":"Scen","exemplar_value":"Exmp"}
LORD = {"bad":0,"flawed":1,"mediocre":2,"solid":3,"strong":4,"exemplar":5}

verdicts = [json.loads(l) for l in (OLD/"verdicts_v4.3.jsonl").open()]
human = {}
for f in sorted((OLD/"failure_catalog").glob("slice_*.md")):
    for m in re.finditer(r"^### ([0-9a-f]{8})[^\n]*\nmy_read: (\w+)", f.read_text(), re.M):
        human[m.group(1)] = m.group(2)

def effective(v):
    ds = {k: (x if isinstance(x, int) else None) for k, x in v["verdict"]["dimension_scores"].items()}
    for c in v["aggregate"].get("caps_applied", []):
        m = re.match(r"(\w+) capped at (\d+)", c)
        if m and isinstance(ds.get(m.group(1)), int):
            ds[m.group(1)] = min(ds[m.group(1)], int(m.group(2)))
    return ds

# build matrix X (n x 10) with np.nan for NA, and analyst ordinal y
rows, y, ids = [], [], []
for v in verdicts:
    ds = effective(v)
    lab = human.get(v["record_id"][:8])
    if lab is None: continue
    rows.append([ds.get(d) if isinstance(ds.get(d), int) else np.nan for d in DIMS])
    y.append(LORD[lab]); ids.append(v["record_id"][:8])
X = np.array(rows, float); y = np.array(y, float)
n = len(X)
print(f"n = {n} records with analyst labels\n")

# ---------- 1. variance / information ----------
print("="*74)
print("1. VARIANCE & INFORMATION CONTENT  (a near-constant dim carries no signal)")
print("="*74)
print(f"{'dim':6s} {'n':>4s} {'mean':>5s} {'sd':>5s} {'var':>6s} {'range':>6s}  interpretation")
for i, d in enumerate(DIMS):
    col = X[:, i]; c = col[~np.isnan(col)]
    sd = c.std(ddof=1); rng = f"{int(c.min())}-{int(c.max())}"
    note = "DEAD — no variance" if sd < 0.6 else ("low spread" if sd < 1.5 else "")
    print(f"{AB[d]:6s} {len(c):>4d} {c.mean():5.2f} {sd:5.2f} {c.var(ddof=1):6.2f} {rng:>6s}  {note}")

# ---------- 2. pairwise Spearman among dims ----------
def rankdata(a):
    a = np.asarray(a, float); order = np.argsort(a, kind="mergesort"); r = np.empty(len(a))
    r[order] = np.arange(len(a))
    # average ties
    _, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    csum = np.cumsum(cnt); starts = csum - cnt
    avg = (starts + csum - 1) / 2.0
    return avg[inv]

def spearman(a, b):
    m = ~np.isnan(a) & ~np.isnan(b)
    if m.sum() < 3: return np.nan
    ra, rb = rankdata(a[m]), rankdata(b[m])
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra**2).sum() * (rb**2).sum())
    return float((ra*rb).sum()/d) if d else np.nan

print("\n"+"="*74)
print("2. INTER-DIMENSION SPEARMAN  (|rho|>=0.70 = merge candidate, pairwise-complete)")
print("="*74)
C = np.zeros((10,10))
for i in range(10):
    for j in range(10):
        C[i,j] = spearman(X[:,i], X[:,j])
hdr = "      " + " ".join(f"{AB[d]:>5s}" for d in DIMS)
print(hdr)
for i, d in enumerate(DIMS):
    print(f"{AB[d]:6s}" + " ".join((f"{C[i,j]:5.2f}" if not np.isnan(C[i,j]) else "   NA") for j in range(10)))
print("\nStrongest off-diagonal pairs:")
pairs = sorted(((C[i,j], DIMS[i], DIMS[j]) for i in range(10) for j in range(i+1,10)
                if not np.isnan(C[i,j])), key=lambda t:-t[0])
for rho, a, b in pairs[:8]:
    flag = "  <-- MERGE CANDIDATE" if rho >= 0.70 else ("  (high)" if rho>=0.6 else "")
    print(f"  {AB[a]:5s} ~ {AB[b]:5s}  rho={rho:+.3f}{flag}")

# ---------- 3. PCA ----------
print("\n"+"="*74)
print("3. PCA  (how many latent factors drive the 10 scores; mean-imputed, standardized)")
print("="*74)
Xi = X.copy()
for i in range(10):
    col = Xi[:,i]; col[np.isnan(col)] = np.nanmean(col)
Z = (Xi - Xi.mean(0)) / Xi.std(0, ddof=1)
cov = np.cov(Z, rowvar=False)
w, Vt = np.linalg.eigh(cov)
idx = np.argsort(w)[::-1]; w = w[idx]; Vt = Vt[:, idx]
tot = w.sum()
print(f"{'PC':>3s} {'eigval':>7s} {'%var':>6s} {'cum%':>6s}")
cum = 0
for k in range(10):
    cum += w[k]/tot*100
    print(f"{k+1:>3d} {w[k]:7.3f} {w[k]/tot*100:6.1f} {cum:6.1f}")
print("\nLoadings on PC1-PC3 (which dims move together):")
print("      " + "  PC1   PC2   PC3")
for i, d in enumerate(DIMS):
    print(f"{AB[d]:6s} {Vt[i,0]:+5.2f} {Vt[i,1]:+5.2f} {Vt[i,2]:+5.2f}")

# ---------- 4. discrimination vs analyst ----------
print("\n"+"="*74)
print("4. DISCRIMINATION vs ANALYST ORDINAL  (external ground truth)")
print("="*74)
print(f"{'dim':6s} {'rho':>6s} {'eta2':>6s}   tier means bad->exemplar")
def eta2(col, y):
    m = ~np.isnan(col); c = col[m]; yy = y[m]
    grand = c.mean(); ss_tot = ((c-grand)**2).sum()
    ss_b = 0
    for g in np.unique(yy):
        cg = c[yy==g]; ss_b += len(cg)*(cg.mean()-grand)**2
    return ss_b/ss_tot if ss_tot else np.nan
for i, d in enumerate(DIMS):
    col = X[:,i]; rho = spearman(col, y); e = eta2(col, y)
    tms = []
    for g in range(6):
        cg = col[(y==g) & ~np.isnan(col)]
        tms.append(f"{cg.mean():4.1f}" if len(cg) else "  - ")
    print(f"{AB[d]:6s} {rho:+.3f} {e:6.3f}   {' '.join(tms)}")

# ---------- 5. incremental value: OLS + drop-one ----------
print("\n"+"="*74)
print("5. INCREMENTAL VALUE  (OLS analyst_ord ~ standardized dims; drop-one Delta-R^2)")
print("="*74)
def ols_r2(cols):
    A = np.column_stack([Z[:,c] for c in cols] + [np.ones(n)])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ beta; ss_res = ((y-pred)**2).sum(); ss_tot = ((y-y.mean())**2).sum()
    return 1 - ss_res/ss_tot, beta
full_r2, beta = ols_r2(list(range(10)))
print(f"Full model R^2 = {full_r2:.3f}  (all 10 standardized dims predicting analyst tier)")
print(f"{'dim':6s} {'std-beta':>9s} {'dropR2':>7s} {'deltaR2':>8s}  interpretation")
order = sorted(range(10), key=lambda i: -abs(beta[i]))
for i in order:
    r2_wo, _ = ols_r2([c for c in range(10) if c != i])
    dr = full_r2 - r2_wo
    note = "redundant (adds ~0)" if dr < 0.005 else ("marginal" if dr < 0.02 else "carries unique signal")
    print(f"{AB[DIMS[i]]:6s} {beta[i]:+9.3f} {r2_wo:7.3f} {dr:+8.4f}  {note}")

# ---------- 6. mutual information dim -> analyst label ----------
print("\n"+"="*74)
print("6. MUTUAL INFORMATION  (dim score -> analyst label, bits; discretized to <=5/6-9/>=... )")
print("="*74)
def mi(col, lab):
    m = ~np.isnan(col); c = col[m].astype(int); l = lab[m]
    # bucket scores into low(<=4) mid(5-6) high(7-8) top(9-10)
    b = np.digitize(c, [5,7,9])
    N = len(c); H = 0.0
    for x in np.unique(b):
        for yv in np.unique(l):
            pxy = ((b==x)&(l==yv)).mean()
            if pxy>0:
                px = (b==x).mean(); py = (l==yv).mean()
                H += pxy*np.log2(pxy/(px*py))
    return H
labs = np.array([LORD_inv for LORD_inv in y])  # y already ordinal
for i, d in enumerate(DIMS):
    print(f"{AB[d]:6s} MI = {mi(X[:,i], y):.3f} bits")

# ---------- 7. gate co-occurrence + unique kills ----------
print("\n"+"="*74)
print("7. GATE STRUCTURE  (which gates are load-bearing vs redundant)")
print("="*74)
def gate_family(f):
    if "scalar_floor_any" in f: return "floor_any:"+f.split()[0]
    if "< floor" in f: return "crit:"+f.split()[0]
    if f.startswith("behavior"): return "behavior"
    if "outcome_held" in f or "rationale abandoned" in f: return "value_stability"
    if "self_contained" in f: return "self_contained"
    return "other"
fails = [v for v in verdicts if not v["aggregate"]["passing"]]
fam_sets = [sorted({gate_family(f) for f in v["aggregate"]["gate_failures"]}) for v in fails]
allg = collections.Counter(g for s in fam_sets for g in s)
unique = collections.Counter(s[0] for s in fam_sets if len(s)==1)
print(f"{'gate family':32s} {'fires':>6s} {'sole-killer':>12s}")
for g, c in allg.most_common():
    print(f"{g:32s} {c:6d} {unique.get(g,0):12d}")
print(f"\nfails with >=2 gate families: {sum(1 for s in fam_sets if len(s)>=2)} / {len(fails)}")

# ---------- 8. threshold calibration ----------
print("\n"+"="*74)
print("8. CALIBRATION vs ANALYST 'USABLE' (solid+)  — is the pass gate placed right?")
print("="*74)
usable = (y >= LORD["solid"]).astype(int)   # ground-truth positive
passing = np.array([1 if verdicts_by_id[i]["aggregate"]["passing"] else 0 for i in ids]) \
          if False else None
# map ids to passing
pmap = {v["record_id"][:8]: v["aggregate"]["passing"] for v in verdicts}
passing = np.array([1 if pmap[i] else 0 for i in ids])
def confusion(pred, truth):
    tp = int(((pred==1)&(truth==1)).sum()); fp = int(((pred==1)&(truth==0)).sum())
    tn = int(((pred==0)&(truth==0)).sum()); fn = int(((pred==0)&(truth==1)).sum())
    prec = tp/(tp+fp) if tp+fp else 0; rec = tp/(tp+fn) if tp+fn else 0
    f1 = 2*prec*rec/(prec+rec) if prec+rec else 0
    acc = (tp+tn)/len(pred)
    den = ((tp+fp)*(tp+fn)*(tn+fp)*(tn+fn))**0.5
    mcc = (tp*tn-fp*fn)/den if den else 0
    return dict(tp=tp,fp=fp,tn=tn,fn=fn,prec=prec,rec=rec,f1=f1,acc=acc,mcc=mcc)
c = confusion(passing, usable)
print(f"Current v4.3 gate vs analyst-usable(solid+): "
      f"prec={c['prec']:.2f} rec={c['rec']:.2f} F1={c['f1']:.2f} acc={c['acc']:.2f} MCC={c['mcc']:.2f}")
print(f"  TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}  "
      f"(FP=passed-but-analyst-mediocre-or-below, FN=failed-but-analyst-solid-plus)")
# what if ground truth is 'strong+'?
strongplus = (y>=LORD["strong"]).astype(int)
c2 = confusion(passing, strongplus)
print(f"Current v4.3 gate vs analyst-strong+:        "
      f"prec={c2['prec']:.2f} rec={c2['rec']:.2f} F1={c2['f1']:.2f} MCC={c2['mcc']:.2f}  "
      f"(TP={c2['tp']} FP={c2['fp']} FN={c2['fn']})")
# pure-mean threshold sweep vs usable
means = np.array([verdicts[0]["aggregate"]["mean"] for _ in range(0)])  # placeholder
meanmap = {v["record_id"][:8]: v["aggregate"]["mean"] for v in verdicts}
mvec = np.array([meanmap[i] for i in ids])
print("\nPure-mean threshold sweep vs analyst-usable(solid+):")
print(f"{'thr':>4s} {'pass%':>6s} {'prec':>5s} {'rec':>5s} {'F1':>5s} {'MCC':>5s}")
for thr in [4.0,4.5,5.0,5.5,6.0,6.5,7.0]:
    pred = (mvec>=thr).astype(int); cc = confusion(pred, usable)
    print(f"{thr:4.1f} {pred.mean()*100:6.0f} {cc['prec']:5.2f} {cc['rec']:5.2f} {cc['f1']:5.2f} {cc['mcc']:5.2f}")
print("\n(Gates add specificity beyond the mean: compare current gate MCC to the best pure-mean MCC.)")
