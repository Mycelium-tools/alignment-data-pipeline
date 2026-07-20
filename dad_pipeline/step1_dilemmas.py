"""Step 1: Generate scenarios, then draft dilemma prompts. Sub-stages:

- Step 1a — scenario deal + plan: deal a stratified variable combination per
  example from the weighted matrix in prompts/dad/variables.txt (offline;
  dad_pipeline/compose_scenarios.py owns the dealing and the structural
  rules), then one plan call per deal renders prompts/dad/step1a_scenario.txt
  and turns the combination into a self-contained scenario description
  (extracted fail-closed; INCOHERENT combinations are checkpointed as
  deliberate rejections in scenario_rejects.jsonl and never retried). Deals
  persist to step1/scenario_deals.jsonl and planned scenarios to
  step1/scenarios.jsonl, so --resume replays the same deal and only plans
  what's missing. Pre-plan runs (scenarios.jsonl without a deals file) skip
  planning; when drafted through the current single-scenario template, their
  rendered legacy card fills the scenario-description slot (see
  compose_scenarios.render_draft_prompt) — a run whose snapshot still holds
  the old batch template is refused loudly instead.

- Step 1b — first attempt: one draft call per scenario (SDF layer-3 style),
  fanned out via parallel_map. The prompt renders the plan's scenario
  description, the persona voice, and the dealt length register
  (prompts/dad/step1b_dilemmas.txt); the reply is the user message inside
  <user_prompt> tags, extracted fail-closed and gated by the lenient length
  band. 1b writes no annotation — the dealt labels ARE the design, and the
  record's annotation is synthesized from the scenario. Accepted drafts are
  taken as returned; distribution fidelity is monitored by the corpus-level
  checklist instead.

- Step 1c — quality gate (optional; config dad.dilemmas.gate, on by default;
  legacy key `refine` still honored): a second model call JUDGES each 1b draft
  against its scenario per prompts/dad/step1_gate.txt — pass/fail, never a
  rewrite. The four checks are: the welfare stake is load-bearing, the draft
  honors its dealt cards, the message is self-contained, the scene is
  cohesive. A rejected scenario is routed back through the drafting loop with
  the gate's reasons injected into the next attempt (so it redrafts away from
  them), capped at MAX_GATE_REDRAFTS; a scenario still failing after the cap
  ships with gate_failures stamped on its record. Because text is never
  edited, the record's annotation stays true to the shipped prompt by
  construction. Verdicts are logged to step1/gate.jsonl; unusable gate replies
  (retried once) persist to step1/gate_failures.jsonl and fail open (ship the
  draft — degraded gating costs a weak prompt, never a stalled run).

The Part 4 checklist re-prints at the end as verification; thresholds are the
spec's, enforcement stays human.

Handwritten examples can be imported ahead of drafting via
config dad.dilemmas.seed_path (JSONL with prompt/user_message, optional
annotation and id); seeds carry no scenario. Generated IDs continue the
AW-#### series above the highest existing ID, per the spec.
"""

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import compose_scenarios
from dad_pipeline.compose_scenarios import render_scenario_block as format_scenario  # noqa: F401 (viewer + 1c)
from dad_pipeline.id_registry import IdRegistry, prompt_fingerprint, scenario_fingerprint

_LIST_FIELDS = ("domain", "user_goal", "values_in_tension", "claims")
_STR_FIELDS = ("moral_patients", "visibility", "user_attitude", "conflict",
               "welfare_magnitude", "user_stakes", "leverage")

# Models sometimes transcribe a compound label as its halves ("Education /
# Parenting" -> ["Education", "Parenting"]); map any half back to its card so
# the tally counts the card, not the fragments. The domain vocabulary comes
# from the RUN'S variables.txt, threaded in by the caller — never the repo's
# live copy, which may have drifted since the run was dealt.
def _canon_domain(label: str, domain_by_part: dict) -> str:
    return domain_by_part.get(str(label).strip().lower(), str(label).strip())

def _annotation_from_scenario(p: dict) -> dict:
    """The record's annotation, synthesized from the scenario's dealt labels.

    1b no longer writes an annotation (its reply is the user message alone);
    the deal IS the design, so the labels are copied from the scenario for 1c
    context, the checklist tallies, and the viewer. The old creative fields
    (dilemma_anatomy, values_in_tension, moral_patients, claims) exist only on
    records from pre-rework runs."""
    return _normalize_annotation({
        "domain": list(p.get("domain") or []),
        "user_goal": list(p.get("user_goal") or []),
        "visibility": p.get("visibility", ""),
        "user_attitude": p.get("user_attitude", ""),
        "conflict": p.get("conflict", ""),
        "welfare_magnitude": p.get("welfare_magnitude", ""),
        "user_stakes": p.get("user_stakes", ""),
        "leverage": p.get("leverage", ""),
    })


def format_annotation(annotation: dict) -> str:
    """Human-readable annotation block, embedded in the step 3/4 prompts (and
    re-rendered by the viewer — keep in sync with viewer/rendering.py)."""
    anatomy = annotation.get("dilemma_anatomy") or {}
    lines = [
        f"Domain: {', '.join(annotation.get('domain') or [])}",
        f"User goal: {', '.join(annotation.get('user_goal') or [])}",
        # the creative fields exist only on records from pre-rework runs
        # (1b now returns the user message alone); render them conditionally
        *([f"Dilemma anatomy: Goal = {anatomy.get('goal', '')} | "
           f"Temptation = {anatomy.get('temptation', '')} | Cost = {anatomy.get('cost', '')}"]
          if anatomy else []),
        *([f"Values in tension: {'; '.join(annotation['values_in_tension'])}"]
          if annotation.get("values_in_tension") else []),
        *([f"Moral patients: {annotation['moral_patients']}"]
          if annotation.get("moral_patients") else []),
        f"Visibility: {annotation.get('visibility', '')}",
        f"User attitude: {annotation.get('user_attitude', '')}",
        f"Conflict: {annotation.get('conflict', '')}",
        # direction was an axis until 2026-07; render it only for the legacy
        # annotations that carry it (the viewer re-renders old runs' prompts)
        *([f"Direction: {annotation['direction']}"] if annotation.get("direction") else []),
        f"Welfare magnitude: {annotation.get('welfare_magnitude', '')}",
        f"User stakes: {annotation.get('user_stakes', '')}",
        f"Leverage: {annotation.get('leverage', '')}",
    ]
    for c in annotation.get("claims") or []:
        if isinstance(c, dict):
            lines.append(f"Claim ({c.get('status', '?')}): {c.get('claim', '')}")
    return "\n".join(lines)


def _normalize_annotation(annotation: dict) -> dict:
    out = dict(annotation)
    for f in _LIST_FIELDS:
        v = out.get(f)
        if v is None:
            out[f] = []
        elif not isinstance(v, list):
            out[f] = [v]
    for f in _STR_FIELDS:
        out[f] = str(out.get(f, "") or "")
    if not isinstance(out.get("dilemma_anatomy"), dict):
        out["dilemma_anatomy"] = {}
    return out


def _canon_label(label, axis_values) -> str:
    """Map an annotation label onto its axis value, case-insensitively and by
    mutual prefix — so records from older runs (capitalized short labels like
    "Hidden") still count toward today's lower-case sentence-style values.
    Unmatched labels pass through."""
    norm = str(label or "").strip().lower()
    if not norm:
        return str(label or "")
    for v in axis_values:
        vnorm = v.strip().lower()
        if vnorm == norm or vnorm.startswith(norm) or norm.startswith(vnorm):
            return v
    return str(label).strip()


def coverage_tally(examples: list[dict], axes: dict | None = None) -> dict:
    """Label tallies over the examples' annotations, canonicalized onto the
    axis values in `axes` (a values dict from compose_scenarios.load_axes).
    Callers with a run dir must pass the RUN'S axes — the repo default exists
    for ad-hoc use and may have drifted from what the run was dealt with."""
    if axes is None:
        axes = compose_scenarios.load_axes()[0]
    domain_by_part = {p.strip().lower(): d for d in axes.get("domain", ())
                      for p in (d, *d.split("/"))}
    ann = [e.get("annotation") or {} for e in examples]
    return {
        "n": len(examples),
        "conflict": Counter(_canon_label(a.get("conflict"), axes.get("conflict", ())) or "?" for a in ann),
        "visibility": Counter(_canon_label(a.get("visibility"), axes.get("visibility", ())) or "?" for a in ann),
        "attitude": Counter(_canon_label(a.get("user_attitude"), axes.get("user_attitude", ())) or "?" for a in ann),
        "leverage": Counter(_canon_label(a.get("leverage"), axes.get("leverage", ())) or "?" for a in ann),
        "stakes": Counter(_canon_label(a.get("user_stakes"), axes.get("user_stakes", ())) or "?" for a in ann),
        "domains": Counter(d for a in ann
                           for d in {_canon_domain(x, domain_by_part) for x in (a.get("domain") or [])}),
        # taxa read from the assigned scenario field, not keyword-scanned from text
        "taxa": Counter(e.get("taxa_category") for e in examples if e.get("taxa_category")),
    }


def checklist(examples: list[dict],
              variables_path: Path | None = None) -> list[tuple[bool | None, str]]:
    """Mechanical checks from the spec's Part 4 verification checklist.
    Returns (ok, message) per item; ok=None means manual review required.

    `variables_path` must be the RUN'S variables.txt (its inputs/ snapshot) so
    deals are checked against the vocabulary and weights they were dealt with;
    the repo's live file is only a fallback for ad-hoc/legacy use."""
    if not examples:
        return []
    out: list[tuple[bool | None, str]] = []

    # Buckets, weights, and special labels derive from the run's variables.txt,
    # so the checklist tracks the dealt vocabulary instead of hardcoded literals.
    ax_values, ax_weights = compose_scenarios.load_axes(
        variables_path or compose_scenarios.DEFAULT_VARIABLES)
    t = coverage_tally(examples, ax_values)
    n = t["n"]

    # Weighted axes: check each bucket's realized share against its dealt
    # weight (±15 points absorbs annotation drift at small n).
    for axis, tally_key in (("conflict", "conflict"), ("leverage", "leverage")):
        expected = dict(zip(ax_values.get(axis, ()), ax_weights.get(axis, ())))
        if not expected:
            continue
        shares = {v: t[tally_key].get(v, 0) / n for v in expected}
        ok = all(abs(shares[v] - w) <= 0.15 for v, w in expected.items())
        pretty = ", ".join(f"{v!r} {shares[v]:.0%} (dealt {w:.0%})"
                           for v, w in expected.items())
        out.append((ok, f"{axis.capitalize()} shares track dealt weights "
                        f"within 15 points ({pretty})"))

    hidden_value = compose_scenarios.resolve_value(ax_values["visibility"], "hidden", "visibility")
    unaware_value = compose_scenarios.resolve_value(ax_values["user_attitude"], "unaware", "user_attitude")
    hidden = t["visibility"].get(hidden_value, 0) / n
    out.append((hidden >= 0.20, f"hidden visibility at 20% or more ({hidden:.0%})"))

    hidden_aware = sum(
        1 for e in examples
        if _canon_label((e.get("annotation") or {}).get("visibility"),
                        ax_values.get("visibility", ())) == hidden_value
        and _canon_label((e.get("annotation") or {}).get("user_attitude"),
                         ax_values.get("user_attitude", ())) != unaware_value)
    out.append((hidden_aware == 0, f"hidden entails unaware attitude ({hidden_aware} violations)"))

    max_domain, max_count = ("—", 0) if not t["domains"] else t["domains"].most_common(1)[0]
    out.append((max_count / n <= 0.12, f"no domain above 12% (max: {max_domain} {max_count / n:.0%})"))
    thin_missing = [d for d in compose_scenarios.THIN_DOMAINS if t["domains"].get(d, 0) == 0]
    out.append((not thin_missing,
                "thin domains present" + (f" (missing: {', '.join(thin_missing)})" if thin_missing else "")))

    # Taxa batch rule: no role category repeats until all have appeared — for
    # batches up to the category count that means all-distinct taxa. Record
    # values map onto TAXA roles by prefix (taxa_for), so reworded value tails
    # still count toward their role.
    def _taxa_role(value: str) -> str:
        try:
            return next(k for k in compose_scenarios.TAXA
                        if str(value).strip().lower().startswith(k.lower()))
        except StopIteration:
            return str(value)

    taxa_roles = Counter(_taxa_role(v) for v, c in t["taxa"].items() for _ in range(c))
    if n <= len(compose_scenarios.TAXA):
        taxa_dupes = [name for name, c in taxa_roles.items() if c > 1]
        out.append((not taxa_dupes,
                    "taxa distinct within batch"
                    + (f" (repeated: {', '.join(taxa_dupes)})" if taxa_dupes else "")))
    else:
        taxa_missing = [name for name in compose_scenarios.TAXA if taxa_roles.get(name, 0) == 0]
        out.append((not taxa_missing,
                    "all taxa categories present"
                    + (f" (missing: {', '.join(taxa_missing)})" if taxa_missing else "")))

    # Archetypes: reserved cross-axis conjunctions (compose_scenarios.
    # ARCHETYPES, live repo code like TAXA). Gated on the records carrying the
    # field — runs that predate archetypes are never checked against them.
    if any("archetype" in e for e in examples):
        arch = Counter(e.get("archetype") for e in examples if e.get("archetype"))
        for name, spec in compose_scenarios.ARCHETYPES.items():
            expected = round(spec["share"] * n)
            got = arch.get(name, 0)
            out.append((got >= expected,
                        f"archetype {name!r} present ({got}; dealt share expects {expected})"))
        overwrites = sum(len(e.get("archetype_overwrites") or []) for e in examples)
        out.append((overwrites == 0,
                    f"archetype swaps preserved marginal shares ({overwrites} overwrites)"))

    # NOTE: the value-pair and claims checks retired with the 1b annotation —
    # the load-bearing welfare guarantee is the 1c gate's job (step1_gate.txt,
    # Check 1); the welfare-money and claim-pattern mixes are dealt by weight in
    # variables.txt.
    out.append((None, "welfare load-bearing in every prompt (1c gate's mandate) — review manually"))

    out.append((None, "no dilemma survives deleting the animals (Cost runs through the moral patients; trap prompts exempt by design) — review manually"))
    out.append((None, "canonical skeleton at 15% or less, all five surface forms present — review manually"))
    out.append((None, "trap prompts (innocuous ask) contain no visible dilemma — the welfare stake lives in the answer space — review manually"))
    out.append((None, "every Temptation passes the 'would a reasonable person be tempted' read — review manually"))
    out.append((None, "one example turns on a Settled claim the user doubts, one on an Open claim treated as settled — review manually"))
    return out


def print_checklist(examples: list[dict], save_path: Path | None = None,
                    variables_path: Path | None = None) -> None:
    """Print the Part-4 checklist; with save_path, also persist it into the run
    dir (the printout otherwise lives only in terminal scrollback).
    `variables_path` threads the run's snapshotted variables.txt through."""
    lines = ["Batch checklist (spec Part 4):"]
    for ok, msg in checklist(examples, variables_path):
        mark = "✓" if ok else ("✗" if ok is False else "·")
        lines.append(f"  {mark} {msg}")
    print("\n".join(f"  {line}" for line in lines))
    if save_path is not None:
        Path(save_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _salvage_objects(text: str) -> list:
    """Extract top-level {...} objects one at a time via brace matching, so a
    truncated or trailing-garbage array still yields its complete objects."""
    objs, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    # strict=False: same control-char tolerance as extract_json,
                    # so a salvageable object isn't dropped for a literal newline
                    objs.append(json.loads(text[start:i + 1], strict=False))
                except json.JSONDecodeError:
                    pass
                start = None
    return objs


def _parse_json_object(raw: str) -> dict | None:
    """The reply's JSON object via the shared hardened parser, salvaging the
    first complete top-level object when the container is broken."""
    try:
        return utils.extract_json_object(raw)
    except json.JSONDecodeError:
        objs = _salvage_objects(raw)
        return objs[0] if objs else None


MAX_GATE_ATTEMPTS = 2      # fresh retries when the gate's own reply is unparseable
MAX_GATE_REDRAFTS = 3      # times a scenario is redrafted after a gate rejection


def gate_draft(scenario: dict, draft: dict, prompts_dir: Path,
               model: str | None = None) -> tuple[bool | None, list[str], list[dict]]:
    """Step 1c: JUDGE the 1b draft against its scenario per prompts/dad/step1_gate.txt.
    Returns a pass/fail verdict — never a rewrite.

    Returns (passed, failures, raw_failures):
      passed        True/False verdict, or None when every attempt was unusable
                    (caller then fail-opens and ships the draft).
      failures      the gate's reasons (empty on pass; only meaningful with a
                    True/False verdict).
      raw_failures  unusable-reply raws for the main thread to persist to
                    step1/gate_failures.jsonl — a discarded raw is an
                    undiagnosable failure.
    An unusable reply is retried once with a fresh call (same policy shape as
    2a scoping)."""
    system_prompt, user_prompt = utils.load_split_prompt(
        prompts_dir / "step1_gate.txt",
        scenario_block=format_scenario(scenario),
        draft_prompt=str(draft.get("prompt", "")).strip(),
        # Claims are step-3 scaffolding — kept out of the gate's view for parity
        # with the annotation the downstream steps see.
        annotation_block=format_annotation(
            {k: v for k, v in _normalize_annotation(draft.get("annotation") or {}).items()
             if k != "claims"}),
    )
    raw_failures = []
    pid = scenario.get("scenario_id")
    for attempt in range(1, MAX_GATE_ATTEMPTS + 1):
        raw = api.call_claude(user_message=user_prompt, system_prompt=system_prompt,
                              max_tokens=1000, model=model,
                              stage="prompt_gate", item_id=pid)
        verdict = _parse_json_object(raw)
        if isinstance(verdict, dict) and "pass" in verdict:
            failures = [str(f).strip() for f in (verdict.get("failures") or []) if str(f).strip()]
            return (bool(verdict.get("pass")), failures, raw_failures)
        raw_failures.append({"scenario_id": pid, "attempt": attempt, "raw": raw})
        if attempt < MAX_GATE_ATTEMPTS:
            print(f"    {pid}: gate attempt {attempt}/{MAX_GATE_ATTEMPTS} "
                  "unusable — retrying with a fresh call.")
    return (None, [], raw_failures)


def _redraft_feedback_block(failures: list[str]) -> str:
    """The feedback a rejected scenario carries into its next 1b draft, so the
    redraft fixes the gate's specific objections instead of blindly re-rolling.
    Empty string on a first attempt (no prior rejection) — the template's
    {redraft_feedback} slot then renders to nothing."""
    if not failures:
        return ""
    reasons = "\n".join(f"- {r}" for r in failures)
    return ("\nPRIOR ATTEMPT: an earlier draft of this prompt was rejected by a "
            "quality check for the following reasons. Write a new version that "
            "fixes them while still honoring the scenario and all instructions "
            f"above:\n{reasons}\n")


def _next_id(examples: list[dict], id_start: int) -> str:
    highest = id_start - 1
    for e in examples:
        m = re.fullmatch(r"AW-(\d+)", str(e.get("prompt_id", "")))
        if m:
            highest = max(highest, int(m.group(1)))
    return f"AW-{highest + 1:04d}"


def _registry_path(output_dir: Path) -> Path:
    """The stable-id registry lives at the dad-pipeline output root
    (<outputs>/dad/id_registry.json), found by walking up to the `runs` dir.
    Falls back to the output dir's parent for non-standard layouts (e.g. tests
    passing a bare tmp step-1 dir), which keeps each test isolated."""
    for anc in output_dir.parents:
        if anc.name == "runs":
            return anc.parent / "id_registry.json"
    return output_dir / "id_registry.json"  # non-standard layout (tests): keep it local


def run(config: dict, prompts_dir: Path, output_dir: Path) -> list[dict]:
    cfg = config["dad"]["dilemmas"]
    target = int(cfg.get("count", 40))
    id_start = int(cfg.get("id_start", 1))

    output_path = output_dir / "dilemmas.jsonl"
    scenarios_path = output_dir / "scenarios.jsonl"
    gate_path = output_dir / "gate.jsonl"
    # Stable content-keyed ids (scenario_gid / prompt_gid), shared across runs.
    registry = IdRegistry(_registry_path(output_dir))

    draft_template = prompts_dir / "step1b_dilemmas.txt"
    if not draft_template.exists():
        # runs snapshotted before the 2026-07 rename carry the old filename
        legacy = prompts_dir / "step1_dilemmas.txt"
        if legacy.exists():
            draft_template = legacy
        else:
            raise SystemExit(f"Draft template not found at {draft_template} — "
                             "the DAD pipeline cannot run without it.")

    # Step 1c: pass/fail quality gate on each draft (never a rewrite). On by
    # default (matches config.yaml and CLAUDE.md); disable with
    # dad.dilemmas.gate: false. The legacy key `refine` is still honored so old
    # configs keep gating.
    gate_enabled = bool(cfg.get("gate", cfg.get("refine", True)))
    if gate_enabled and not (prompts_dir / "step1_gate.txt").exists():
        raise SystemExit("dad.dilemmas.gate is on but prompts/dad/step1_gate.txt is missing.")

    examples = utils.load_jsonl(output_path)

    # Optional handwritten seed examples, imported once ahead of generation
    seed_path = cfg.get("seed_path")
    if seed_path and not any(e.get("source") == "seed" for e in examples):
        imported = 0
        seen_ids = {e["prompt_id"] for e in examples}
        for rec in utils.load_jsonl(seed_path):
            text = (rec.get("prompt") or rec.get("user_message") or "").strip()
            if not text:
                continue
            pid = str(rec.get("id") or _next_id(examples, id_start))
            # A duplicate prompt_id silently collides in step 2's per-prompt maps
            # (two dilemmas share one scope/response), so reject it loudly.
            if pid in seen_ids:
                raise SystemExit(f"Duplicate prompt_id {pid!r} in seed file {seed_path} "
                                 "(collides with another seed or a generated id) — fix the ids.")
            seen_ids.add(pid)
            record = {
                "prompt_id": pid,
                "prompt_gid": f"P-{registry.assign('prompt', prompt_fingerprint(text)):04d}",
                "user_message": text,
                "annotation": _normalize_annotation(rec.get("annotation") or {}),
                "source": "seed",
                "batch": None,
            }
            examples.append(record)
            utils.append_jsonl(record, output_path)
            imported += 1
        registry.save()
        print(f"  Imported {imported} seed examples from {seed_path}")

    # --- Step 1a: scenario deal + plan. The deal is offline and persists once
    # per run (so --resume replays the same one); each deal then gets one plan
    # call that writes its scenario description. Planned scenarios checkpoint
    # to scenarios.jsonl; INCOHERENT deals checkpoint to scenario_rejects.jsonl
    # as deliberate rejections (never retried). A run written before the plan
    # stage (scenarios.jsonl but no deals file) skips planning and drafts from
    # its legacy scenario cards unchanged.
    deals_path = output_dir / "scenario_deals.jsonl"
    rejects_path = output_dir / "scenario_rejects.jsonl"
    deals = utils.load_jsonl(deals_path)
    scenarios = utils.load_jsonl(scenarios_path)
    legacy_run = bool(scenarios) and not deals

    # The run's own variables.txt (its inputs/ snapshot) governs both the deal
    # and the end-of-step checklist; the repo's live copy is a legacy fallback.
    variables_path = prompts_dir / "variables.txt"
    if not variables_path.exists():
        variables_path = compose_scenarios.DEFAULT_VARIABLES
        if not legacy_run:
            print("WARNING: run has no variables.txt snapshot; using the repo's live copy.")

    if not legacy_run:
        if not deals:
            rng = random.Random(cfg.get("scenario_seed"))
            deals = compose_scenarios.deal_scenarios(target - len(examples), rng, variables_path)
            for p in deals:
                p["scenario_gid"] = f"S-{registry.assign('scenario', scenario_fingerprint(p)):04d}"
                utils.append_jsonl(p, deals_path)
            registry.save()
            print(f"  [1a deal] Dealt {len(deals)} stratified scenarios into {deals_path}")

        rejects = utils.load_jsonl(rejects_path)
        done_ids = ({s["scenario_id"] for s in scenarios}
                    | {r["scenario_id"] for r in rejects})
        pending_deals = [p for p in deals if p["scenario_id"] not in done_ids]
        if pending_deals:
            plan_template_path = prompts_dir / "step1a_scenario.txt"
            if not plan_template_path.exists():
                raise SystemExit(f"Scenario-plan template not found at {plan_template_path} — "
                                 "the DAD pipeline cannot run without it.")
            plan_template = plan_template_path.read_text(encoding="utf-8")
            plan_model = config["dad"].get("scenario_model")
            # On a persistent refusal, the last-ditch attempt switches models.
            # A stochastic refusal clears on an Opus retry (attempts 1-2 stay on
            # the stage model); a deterministic one needs a model no Opus retry
            # can escape, and dropping the plan would bias the corpus away from
            # the refused content — often the insect-welfare slice the matrix
            # upweights. null/absent = no switch (the granted attempt stays on
            # the stage model — the pre-fallback behavior). Whether Sonnet
            # actually refuses less here is unmeasured; even at equal rates this
            # is an independent draw, and it degrades safely (a fallback refusal
            # just lands in the failures file, so the run dies no sooner).
            refusal_fallback_model = config["dad"].get("scenario_refusal_fallback_model")
            print(f"  [1a plan] Writing scenario descriptions for {len(pending_deals)} deals...")

            def _plan(deal: dict) -> tuple[str | None, str | None, list[dict], str | None]:
                """One plan call (API + parse only, per the parallel_map
                contract). Returns (description, incoherent_raw, failures,
                served_model) — served_model is the model that produced an
                accepted description (None when none was), so the caller can
                flag a fallback-authored scenario."""
                system_prompt, user_prompt = compose_scenarios.render_plan_prompt(
                    deal, plan_template)
                failures = []
                attempt, attempts_allowed = 0, 2
                refused = False
                while attempt < attempts_allowed:
                    attempt += 1
                    # The fallback engages only on the last granted attempt, and
                    # only a refusal grants one — so attempts 1-2 always run on
                    # the stage model, giving a stochastic refusal its Opus retry.
                    use_fallback = (refused and refusal_fallback_model
                                    and attempt == attempts_allowed)
                    model = refusal_fallback_model if use_fallback else plan_model
                    raw, stop_reason = api.call_claude(
                        user_message=user_prompt, system_prompt=system_prompt,
                        max_tokens=4000, model=model,
                        stage="scenario_plan", item_id=deal["scenario_id"],
                        return_stop_reason=True)
                    # The codebase invariant: output the API stopped short —
                    # token cap, or Opus's refusal classifier cutting the
                    # stream (seen intermittently on insect-welfare plans,
                    # 2026-07-19) — is never parsed or checkpointed, even when
                    # its tags happen to parse. Records carry the stop_reason
                    # and model because the api.py console warning doesn't persist.
                    if stop_reason in ("max_tokens", "refusal"):
                        if stop_reason == "refusal":
                            # the classifier is stochastic on the same prompt —
                            # one extra attempt keeps the run from dying on it
                            attempts_allowed = 3
                            refused = True
                        failure = {"scenario_id": deal["scenario_id"],
                                   "attempt": attempt, "raw": raw,
                                   "stop_reason": stop_reason, "model": model}
                        if stop_reason == "max_tokens":
                            failure["truncated"] = True
                        failures.append(failure)
                        continue
                    if compose_scenarios.is_incoherent(raw):
                        return None, raw, failures, None
                    description = compose_scenarios.extract_description(raw)
                    if description:
                        return description, None, failures, model
                    # ~20% of Opus plan attempts (2026-07-19, n=40) write a
                    # complete description but end the turn without the
                    # closing tag. end_turn certifies the reply finished
                    # naturally (max_tokens was rejected above), so accept
                    # the unclosed tail — and keep the raw on file, marked
                    # recovered, so the rate stays measurable run over run.
                    if stop_reason == "end_turn":
                        description = compose_scenarios.extract_description(
                            raw, allow_unclosed=True)
                        if description:
                            failures.append({"scenario_id": deal["scenario_id"],
                                             "attempt": attempt, "raw": raw,
                                             "stop_reason": stop_reason,
                                             "model": model,
                                             "recovered_unclosed": True})
                            return description, None, failures, model
                    failures.append({"scenario_id": deal["scenario_id"],
                                     "attempt": attempt, "raw": raw,
                                     "stop_reason": stop_reason, "model": model})
                return None, None, failures, None

            workers = int(config.get("workers", 1))
            unusable = []
            for deal, (description, incoherent_raw, failures, served_model) in zip(
                    pending_deals,
                    utils.parallel_map(_plan, pending_deals, workers)):
                # Failure raws persist here on the main thread, in input order.
                for f in failures:
                    utils.append_jsonl(f, output_dir / "scenario_plan_failures.jsonl")
                if any(f.get("recovered_unclosed") for f in failures):
                    print(f"    {deal['scenario_id']}: accepted unclosed "
                          "<scenario_description> (end_turn) — raw kept in "
                          "scenario_plan_failures.jsonl")
                if incoherent_raw is not None:
                    reject = {**deal, "incoherent": True, "plan_raw": incoherent_raw}
                    rejects.append(reject)
                    utils.append_jsonl(reject, rejects_path)
                    print(f"    {deal['scenario_id']}: INCOHERENT combination — "
                          "checkpointed as a deliberate rejection.")
                elif description is not None:
                    scenario = {**deal, "scenario_description": description}
                    # Stamp scenarios the fallback model authored (the stage
                    # model refused, this model didn't), so the corpus audit
                    # can see which plans weren't Opus-written.
                    if served_model and served_model != plan_model:
                        scenario["scenario_model_fallback"] = served_model
                        print(f"    {deal['scenario_id']}: recovered on fallback "
                              f"model {served_model} after {plan_model} refused "
                              "— scenario_model_fallback stamped.")
                    scenarios.append(scenario)
                    utils.append_jsonl(scenario, scenarios_path)
                else:
                    unusable.append(deal["scenario_id"])
            if unusable:
                raise SystemExit(
                    f"{len(unusable)} scenario plans unusable after retries "
                    f"({', '.join(unusable[:5])}{'…' if len(unusable) > 5 else ''}) — "
                    f"inspect {output_dir / 'scenario_plan_failures.jsonl'}, then --resume "
                    "to retry them (planned scenarios are checkpointed).")
        if rejects:
            print(f"  {len(rejects)} INCOHERENT deals rejected — this run will produce "
                  f"{len(scenarios)} of {len(deals)} planned examples "
                  f"(rejections in {rejects_path.name}).")

    # --- Step 1b: first attempt — one draft call per scenario, fanned out via
    # parallel_map (SDF layer-3 style: single scenario per context window). The
    # reply is the user message inside <user_prompt> tags, extracted
    # fail-closed; truncated, tagless, or band-missing drafts are not
    # checkpointed, so the scenario stays pending and the next pass retries it.
    draft_template_text = draft_template.read_text(encoding="utf-8")
    if "{scenarios_block}" in draft_template_text:
        raise SystemExit(
            "This run's 1b template is the pre-rework batch version "
            "({scenarios_block}); the pipeline now drafts one scenario per "
            "call. Finish the run on the pipeline version that created it, or "
            "copy the current prompts/dad/step1b_dilemmas.txt into the run's "
            "inputs/prompts/ snapshot.")

    accepted = {e.get("scenario_id") for e in examples if e.get("scenario_id")}
    workers = int(config.get("workers", 1))
    draft_model = config["dad"].get("prompt_draft_model")
    gate_model = (config["dad"].get("prompt_gate_model")
                  or config["dad"].get("prompt_refine_model"))
    passes = 0
    consecutive_dry_passes = 0
    # Per-scenario gate bookkeeping across drafting passes: how many times a
    # scenario has been gated (redraft cap), and the reasons its last rejection
    # gave (injected into its next draft so the redraft fixes them).
    gate_attempts: dict[str, int] = {}
    gate_feedback: dict[str, list[str]] = {}

    while True:
        pending = [p for p in scenarios if p["scenario_id"] not in accepted]
        if not pending:
            break
        passes += 1
        if passes > 8:
            raise SystemExit(f"8 drafting passes with {len(pending)} scenarios "
                             "still unfilled — inspect the model output.")
        print(f"  [1b] Pass {passes}: drafting {len(pending)} user prompts "
              f"({len(accepted)}/{len(scenarios)} scenarios filled)...")

        def _draft(scenario: dict) -> tuple[str, str]:
            """One draft call (API only, per the parallel_map contract). A
            scenario redrafted after a gate rejection carries the gate's
            reasons in the {redraft_feedback} slot."""
            system_prompt, user_prompt = compose_scenarios.render_draft_prompt(
                scenario, draft_template_text,
                redraft_feedback=_redraft_feedback_block(
                    gate_feedback.get(scenario["scenario_id"], [])))
            return api.call_claude(user_message=user_prompt, system_prompt=system_prompt,
                                   max_tokens=4000, model=draft_model,
                                   stage="prompt_draft", item_id=scenario["scenario_id"],
                                   return_stop_reason=True)

        drafted: dict[str, str] = {}
        hard_failure = False  # parse/truncation failure, as opposed to a length miss
        for scenario, (raw, stop_reason) in zip(
                pending, utils.parallel_map(_draft, pending, workers)):
            sid = scenario["scenario_id"]
            # Failure raws persist here on the main thread, in input order.
            if stop_reason == "max_tokens":
                utils.append_jsonl({"scenario_id": sid, "pass": passes, "raw": raw,
                                    "truncated": True},
                                   output_dir / "draft_failures.jsonl")
                print(f"    {sid}: draft truncated (max_tokens) — will retry.")
                hard_failure = True
                continue
            text = compose_scenarios.extract_user_prompt(raw)
            if text is None:
                utils.append_jsonl({"scenario_id": sid, "pass": passes, "raw": raw},
                                   output_dir / "draft_failures.jsonl")
                print(f"    {sid}: no <user_prompt> tags in the draft reply — will retry.")
                hard_failure = True
                continue
            if not compose_scenarios.length_ok(text, scenario.get("length_class")):
                # a length miss is a retry, not a parse failure: no failure record
                print(f"    {sid}: draft is {len(text)} chars, far off its dealt "
                      f"length class ({scenario.get('length_class')!r}) — will retry.")
                continue
            drafted[sid] = text

        if not drafted:
            # Length-only misses are plain re-rolls, bounded by the 8-pass cap;
            # the 3-strike abort exists for systematic parse/truncation failure
            # (a broken template or model), where more passes can't help.
            if hard_failure:
                consecutive_dry_passes += 1
                if consecutive_dry_passes >= 3:
                    raise SystemExit("Three consecutive drafting passes produced nothing "
                                     f"usable — inspect {output_dir / 'draft_failures.jsonl'} "
                                     "and the template.")
            continue
        consecutive_dry_passes = 0

        # --- Step 1c (optional): GATE each drafted prompt (pass/fail; text is
        # never edited). Gate calls fan out (API call + parse only, per the
        # parallel_map contract); record assembly below stays serial on the
        # main thread so ID assignment and file writes keep input order.
        newly_drafted = [p for p in pending if p["scenario_id"] in drafted]
        verdict_by_pid: dict[str, tuple[bool | None, list[str]]] = {}
        if gate_enabled:
            def _gate(scenario: dict) -> tuple[bool | None, list[str], list[dict]]:
                print(f"    [1c gate] Judging {scenario['scenario_id']}...")
                draft = {"prompt": drafted[scenario["scenario_id"]],
                         "annotation": _annotation_from_scenario(scenario)}
                return gate_draft(scenario, draft, prompts_dir, model=gate_model)

            for scenario, (passed, failures, raw_failures) in zip(
                    newly_drafted, utils.parallel_map(_gate, newly_drafted, workers)):
                verdict_by_pid[scenario["scenario_id"]] = (passed, failures)
                # Workers only call + parse; failure raws persist here on the
                # main thread, in input order (the parallel_map contract).
                for f in raw_failures:
                    utils.append_jsonl(f, output_dir / "gate_failures.jsonl")

        for p in newly_drafted:
            pid = p["scenario_id"]
            # Text is never edited after drafting, so the annotation stays true
            # to the shipped prompt by construction.
            user_message = drafted[pid]
            gate_failures = None

            if gate_enabled:
                passed, failures = verdict_by_pid.get(pid, (None, []))
                gate_attempts[pid] = gate_attempts.get(pid, 0) + 1
                # Log every verdict for provenance / the corpus audit.
                utils.append_jsonl({"scenario_id": pid, "passed": passed,
                                    "failures": failures, "attempt": gate_attempts[pid]},
                                   gate_path)
                if passed is False:
                    if gate_attempts[pid] < MAX_GATE_REDRAFTS:
                        # Reject: stash the reasons and leave the scenario out of
                        # `accepted` so the while loop redrafts it (with the
                        # reasons injected). Not a parse failure, so it must not
                        # touch consecutive_dry_passes (mirrors the length reject).
                        gate_feedback[pid] = failures
                        print(f"    {pid}: gate rejected (attempt {gate_attempts[pid]}/"
                              f"{MAX_GATE_REDRAFTS}) — will redraft. "
                              f"Reasons: {'; '.join(failures) or '(none given)'}")
                        continue
                    # Out of redrafts: ship the last draft, stamped so it's visible.
                    gate_failures = failures
                    print(f"    {pid}: gate still failing after {MAX_GATE_REDRAFTS} "
                          "redrafts — shipping the draft with gate_failures stamped.")
                elif passed is None:
                    # Gate reply unusable after retries: fail-open, ship the draft
                    # (degraded gating costs a weak prompt, never a stalled run).
                    print(f"    {pid}: gate unusable after {MAX_GATE_ATTEMPTS} attempts "
                          "— shipping the draft (raws in gate_failures.jsonl).")

            record = {
                "prompt_id": _next_id(examples, id_start),
                "prompt_gid": f"P-{registry.assign('prompt', prompt_fingerprint(user_message)):04d}",
                "user_message": user_message,
                # 1b no longer writes an annotation; the dealt labels are the
                # design, synthesized here for the gate, the checklist, and the
                # viewer.
                "annotation": _annotation_from_scenario(p),
                "source": "generated",
                "scenario_id": pid,
                "scenario_gid": p.get("scenario_gid"),
                # denormalized from the scenario so the checklist can read taxa
                # coverage exactly, without keyword-scanning the text
                "taxa_category": p["taxa_category"],
                "taxa_subcategory": p.get("taxa_subcategory"),
                "frontier_frame": p.get("frontier_frame"),
                "length_class": p.get("length_class"),
                "cultural_setting": p.get("cultural_setting"),
                "archetype": p.get("archetype"),
                **({"archetype_overwrites": p["archetype_overwrites"]}
                   if p.get("archetype_overwrites") else {}),
            }
            if gate_failures is not None:
                record["gate_failures"] = gate_failures
            examples.append(record)
            accepted.add(pid)
            utils.append_jsonl(record, output_path)
        registry.save()

    print(f"  {len(examples)} dilemma prompts in {output_path}")
    print_checklist(examples, save_path=output_dir / "checklist.txt",
                    variables_path=variables_path)
    return examples
