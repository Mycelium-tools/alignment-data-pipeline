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
  planning and draft from their legacy scenario cards unchanged.

- Step 1b — first attempt: the model drafts each user prompt to fit its
  scenario (binding labels + the plan's description) and completes the
  descriptive annotation fields, per the instructions in
  prompts/dad/step1b_dilemmas.txt. Drafting runs in batches; a draft missing
  from a batch's output is re-requested, and accepted drafts are taken as
  returned — there is no per-example adherence check; distribution fidelity
  is monitored by the corpus-level checklist instead.

- Step 1c — prompt rewrite (optional; config dad.dilemmas.refine, on by
  default): a second model call rewrites each 1b draft's prompt text per the
  specifications in prompts/dad/step1_refine.txt. The 1b draft is kept on the
  record (draft_user_message + refine_notes) and the before/after is logged
  to step1/refinements.jsonl.

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

# Welfare (or the moral patients' interests under another name) must sit on one
# side of at least one value pair — the spec's load-bearing rule (1.5 / field 5).
_WELFARE_PAIR_PROBES = ("welfare", "suffering", "flourishing", "sentien",
                        "interests", "wellbeing", "well-being", "well being")

# Models sometimes transcribe a compound label as its halves ("Education /
# Parenting" -> ["Education", "Parenting"]); map any half back to its card so
# the tally counts the card, not the fragments. Built lazily from the repo's
# variables.txt (the domain vocabulary now lives there, not in code).
_DOMAIN_BY_PART: dict[str, str] | None = None


def _domain_values() -> tuple[str, ...]:
    values, _ = compose_scenarios.load_axes()
    return tuple(values.get("domain", ()))


def _canon_domain(label: str) -> str:
    global _DOMAIN_BY_PART
    if _DOMAIN_BY_PART is None:
        _DOMAIN_BY_PART = {p.strip().lower(): d for d in _domain_values()
                           for p in (d, *d.split("/"))}
    return _DOMAIN_BY_PART.get(str(label).strip().lower(), str(label).strip())

def _welfare_in_pairs(annotation: dict) -> bool:
    return any(any(k in _norm_pair(p) for k in _WELFARE_PAIR_PROBES)
               for p in (annotation.get("values_in_tension") or []))


def format_annotation(annotation: dict) -> str:
    """Human-readable annotation block, embedded in the step 3/4 prompts (and
    re-rendered by the viewer — keep in sync with viewer/rendering.py)."""
    anatomy = annotation.get("dilemma_anatomy") or {}
    lines = [
        f"Domain: {', '.join(annotation.get('domain') or [])}",
        f"User goal: {', '.join(annotation.get('user_goal') or [])}",
        f"Dilemma anatomy: Goal = {anatomy.get('goal', '')} | "
        f"Temptation = {anatomy.get('temptation', '')} | Cost = {anatomy.get('cost', '')}",
        f"Values in tension: {'; '.join(annotation.get('values_in_tension') or [])}",
        f"Moral patients: {annotation.get('moral_patients', '')}",
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


def _norm_pair(pair: str) -> str:
    parts = [p.strip().lower() for p in re.split(r"↔|<->|<>|\bvs\b", str(pair)) if p.strip()]
    return " ↔ ".join(sorted(parts))


_AXIS_VALUES: dict | None = None


def _axes() -> dict:
    """The repo variables.txt axes, parsed once — the checklist's buckets and
    special labels derive from the live file, never hardcoded literals."""
    global _AXIS_VALUES
    if _AXIS_VALUES is None:
        _AXIS_VALUES = compose_scenarios.load_axes()[0]
    return _AXIS_VALUES


def _canon_label(label, axis: str) -> str:
    """Map an annotation label onto its variables.txt value for `axis`,
    case-insensitively and by mutual prefix — so records from older runs
    (capitalized short labels like "Hidden") still count toward today's
    lower-case sentence-style values. Unmatched labels pass through."""
    norm = str(label or "").strip().lower()
    if not norm:
        return str(label or "")
    for v in _axes().get(axis, ()):
        vnorm = v.strip().lower()
        if vnorm == norm or vnorm.startswith(norm) or norm.startswith(vnorm):
            return v
    return str(label).strip()


def coverage_tally(examples: list[dict]) -> dict:
    ann = [e.get("annotation") or {} for e in examples]
    return {
        "n": len(examples),
        "conflict": Counter(_canon_label(a.get("conflict"), "conflict") or "?" for a in ann),
        "visibility": Counter(_canon_label(a.get("visibility"), "visibility") or "?" for a in ann),
        "attitude": Counter(_canon_label(a.get("user_attitude"), "user_attitude") or "?" for a in ann),
        "leverage": Counter(_canon_label(a.get("leverage"), "leverage") or "?" for a in ann),
        "stakes": Counter(_canon_label(a.get("user_stakes"), "user_stakes") or "?" for a in ann),
        "domains": Counter(d for a in ann for d in {_canon_domain(x) for x in (a.get("domain") or [])}),
        "value_pairs": Counter(_norm_pair(p) for a in ann for p in (a.get("values_in_tension") or [])),
        # taxa read from the assigned scenario field, not keyword-scanned from text
        "taxa": Counter(e.get("taxa_category") for e in examples if e.get("taxa_category")),
    }


def checklist(examples: list[dict]) -> list[tuple[bool | None, str]]:
    """Mechanical checks from the spec's Part 4 verification checklist.
    Returns (ok, message) per item; ok=None means manual review required."""
    if not examples:
        return []
    t = coverage_tally(examples)
    n = t["n"]
    out: list[tuple[bool | None, str]] = []

    # Buckets, weights, and special labels derive from variables.txt, so the
    # checklist tracks the live vocabulary instead of hardcoded literals.
    # Weighted axes: check each bucket's realized share against its dealt
    # weight (±15 points absorbs annotation drift at small n).
    ax_values, ax_weights = compose_scenarios.load_axes()
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

    hidden_value = compose_scenarios.resolve_value(_axes()["visibility"], "hidden", "visibility")
    unaware_value = compose_scenarios.resolve_value(_axes()["user_attitude"], "unaware", "user_attitude")
    hidden = t["visibility"].get(hidden_value, 0) / n
    out.append((hidden >= 0.20, f"hidden visibility at 20% or more ({hidden:.0%})"))

    hidden_aware = sum(
        1 for e in examples
        if _canon_label((e.get("annotation") or {}).get("visibility"), "visibility") == hidden_value
        and _canon_label((e.get("annotation") or {}).get("user_attitude"), "user_attitude") != unaware_value)
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

    wm = sum(c for pair, c in t["value_pairs"].items() if "welfare" in pair and "money" in pair)
    out.append((wm / n <= 0.25, f"welfare ↔ money at 25% or less ({wm / n:.0%})"))
    out.append((len(t["value_pairs"]) >= 4, f"at least 4 distinct value pairs ({len(t['value_pairs'])})"))

    no_welfare = [str(e.get("prompt_id", "?")) for e in examples
                  if not _welfare_in_pairs(e.get("annotation") or {})]
    out.append((not no_welfare,
                "welfare on one side of at least one value pair in every example (load-bearing rule)"
                + (f" (missing: {', '.join(no_welfare[:5])}{'…' if len(no_welfare) > 5 else ''})"
                   if no_welfare else "")))

    no_claims = sum(1 for e in examples if not (e.get("annotation") or {}).get("claims"))
    out.append((no_claims == 0, f"Claims field present on every example ({no_claims} empty)"))

    out.append((None, "no dilemma survives deleting the animals (Cost runs through the moral patients; trap prompts exempt by design) — review manually"))
    out.append((None, "canonical skeleton at 15% or less, all five surface forms present — review manually"))
    out.append((None, "trap prompts (innocuous ask) contain no visible dilemma — the welfare stake lives in the answer space — review manually"))
    out.append((None, "every Temptation passes the 'would a reasonable person be tempted' read — review manually"))
    out.append((None, "one example turns on a Settled claim the user doubts, one on an Open claim treated as settled — review manually"))
    return out


def print_checklist(examples: list[dict], save_path: Path | None = None) -> None:
    """Print the Part-4 checklist; with save_path, also persist it into the run
    dir (the printout otherwise lives only in terminal scrollback)."""
    lines = ["Batch checklist (spec Part 4):"]
    for ok, msg in checklist(examples):
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


def _parse_json_array(raw: str) -> list:
    """The reply's JSON array via the shared hardened parser
    (utils.extract_json: fences/prose/control-chars tolerated), falling back to
    object-by-object salvage for truncated or wrong-shaped containers."""
    try:
        return utils.extract_json_array(raw)
    except json.JSONDecodeError:
        return _salvage_objects(raw)


def _parse_json_object(raw: str) -> dict | None:
    """The reply's JSON object via the shared hardened parser, salvaging the
    first complete top-level object when the container is broken."""
    try:
        return utils.extract_json_object(raw)
    except json.JSONDecodeError:
        objs = _salvage_objects(raw)
        return objs[0] if objs else None


MAX_REFINE_ATTEMPTS = 2


def refine_draft(scenario: dict, draft: dict, prompts_dir: Path,
                 model: str | None = None) -> tuple[dict | None, list[dict]]:
    """Step 1c: rewrite the 1b draft's PROMPT TEXT so it follows the specifications in prompts/dad/step1_refine.txt.

    Returns (refined, failures): an unusable reply is retried once with a
    fresh call (same policy shape as 2a scoping); every unusable raw is
    returned in `failures` for the main thread to persist to
    step1/refine_failures.jsonl — a discarded raw is an undiagnosable failure.
    refined is None when all attempts were unusable (caller keeps the 1b
    draft and stamps refine_failed on the record)."""
    system_prompt, user_prompt = utils.load_split_prompt(
        prompts_dir / "step1_refine.txt",
        scenario_block=format_scenario(scenario),
        draft_prompt=str(draft.get("prompt", "")).strip(),
        # Claims are step-3 scaffolding — kept out of 1c's view so the rewriter
        # doesn't echo claim text into the user's message.
        annotation_block=format_annotation(
            {k: v for k, v in _normalize_annotation(draft.get("annotation") or {}).items()
             if k != "claims"}),
    )
    failures = []
    pid = scenario.get("scenario_id")
    for attempt in range(1, MAX_REFINE_ATTEMPTS + 1):
        raw = api.call_claude(user_message=user_prompt, system_prompt=system_prompt,
                              max_tokens=4000, model=model,
                              stage="prompt_refine", item_id=pid)
        refined = _parse_json_object(raw)
        if isinstance(refined, dict) and str(refined.get("prompt", "")).strip():
            return ({"prompt": str(refined["prompt"]).strip(),
                     "notes": str(refined.get("notes", "")).strip()}, failures)
        failures.append({"scenario_id": pid, "attempt": attempt, "raw": raw})
        if attempt < MAX_REFINE_ATTEMPTS:
            print(f"    {pid}: refine attempt {attempt}/{MAX_REFINE_ATTEMPTS} "
                  "unusable — retrying with a fresh call.")
    return (None, failures)


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
    batch_size = int(cfg.get("batch_size", 10))
    id_start = int(cfg.get("id_start", 1))

    output_path = output_dir / "dilemmas.jsonl"
    batches_path = output_dir / "batches.jsonl"
    scenarios_path = output_dir / "scenarios.jsonl"
    refinements_path = output_dir / "refinements.jsonl"
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

    # Step 1c: review-and-rewrite each draft. On by default (matches config.yaml
    # and CLAUDE.md); disable with dad.dilemmas.refine: false.
    refine_enabled = bool(cfg.get("refine", True))
    if refine_enabled and not (prompts_dir / "step1_refine.txt").exists():
        raise SystemExit("dad.dilemmas.refine is on but prompts/dad/step1_refine.txt is missing.")

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

    if not legacy_run:
        if not deals:
            rng = random.Random(cfg.get("scenario_seed"))
            variables_path = prompts_dir / "variables.txt"
            if not variables_path.exists():
                variables_path = compose_scenarios.DEFAULT_VARIABLES
                print("WARNING: run has no variables.txt snapshot; using the repo's live copy.")
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
            print(f"  [1a plan] Writing scenario descriptions for {len(pending_deals)} deals...")

            def _plan(deal: dict) -> tuple[str | None, str | None, list[dict]]:
                """One plan call (API + parse only, per the parallel_map
                contract). Returns (description, incoherent_raw, failures)."""
                system_prompt, user_prompt = compose_scenarios.render_plan_prompt(
                    deal, plan_template)
                failures = []
                for attempt in (1, 2):
                    raw, stop_reason = api.call_claude(
                        user_message=user_prompt, system_prompt=system_prompt,
                        max_tokens=4000, model=plan_model,
                        stage="scenario_plan", item_id=deal["scenario_id"],
                        return_stop_reason=True)
                    # The codebase invariant: truncated output is never used or
                    # checkpointed, even when its tags happen to parse.
                    if stop_reason == "max_tokens":
                        failures.append({"scenario_id": deal["scenario_id"],
                                         "attempt": attempt, "raw": raw,
                                         "truncated": True})
                        continue
                    if compose_scenarios.is_incoherent(raw):
                        return None, raw, failures
                    description = compose_scenarios.extract_description(raw)
                    if description:
                        return description, None, failures
                    failures.append({"scenario_id": deal["scenario_id"],
                                     "attempt": attempt, "raw": raw})
                return None, None, failures

            workers = int(config.get("workers", 1))
            unusable = []
            for deal, (description, incoherent_raw, failures) in zip(
                    pending_deals,
                    utils.parallel_map(_plan, pending_deals, workers)):
                # Failure raws persist here on the main thread, in input order.
                for f in failures:
                    utils.append_jsonl(f, output_dir / "scenario_plan_failures.jsonl")
                if incoherent_raw is not None:
                    reject = {**deal, "incoherent": True, "plan_raw": incoherent_raw}
                    rejects.append(reject)
                    utils.append_jsonl(reject, rejects_path)
                    print(f"    {deal['scenario_id']}: INCOHERENT combination — "
                          "checkpointed as a deliberate rejection.")
                elif description is not None:
                    scenario = {**deal, "scenario_description": description}
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

    # --- Step 1b: first attempt — draft a prompt + annotation for each scenario.
    accepted = {e.get("scenario_id") for e in examples if e.get("scenario_id")}
    consecutive_failures = 0
    max_calls = 8 * max(1, (len(scenarios) + batch_size - 1) // batch_size)
    calls = 0

    while True:
        pending = [p for p in scenarios if p["scenario_id"] not in accepted]
        if not pending:
            break
        calls += 1
        if calls > max_calls:
            raise SystemExit(f"Exceeded {max_calls} generation calls with "
                             f"{len(pending)} scenarios still unfilled — inspect the model output.")
        batch = pending[:batch_size]
        batch_no = len(utils.load_jsonl(batches_path)) + 1
        scenarios_block = "\n\n".join(format_scenario(p) for p in batch)

        print(f"  [1b] Batch {batch_no}: drafting {len(batch)} examples "
              f"({len(accepted)}/{len(scenarios)} scenarios filled)...")
        system_prompt, user_prompt = utils.load_split_prompt(
            draft_template,
            count=len(batch), scenarios_block=scenarios_block,
        )
        # Generous ceiling: the drafting prompt is large and richly-annotated
        # batches can run long; truncation is the main cause of unusable output.
        batch_pids = {p["scenario_id"] for p in batch}
        # One call drafts the whole batch — tag it with every scenario id it
        # serves so per-record stats can find it (viewer splits on commas).
        raw = api.call_claude(user_message=user_prompt, system_prompt=system_prompt,
                              max_tokens=16000,
                              model=config["dad"].get("prompt_draft_model"),
                              stage="prompt_draft",
                              item_id=",".join(sorted(batch_pids)))

        by_pid = {}
        scen_by_pid = {p["scenario_id"]: p for p in batch}
        length_rejects = 0
        for x in _parse_json_array(raw):
            if (isinstance(x, dict) and str(x.get("prompt", "")).strip()
                    and isinstance(x.get("annotation"), dict)
                    and x.get("scenario_id") in batch_pids):
                # Lenient length gate: a draft that egregiously misses its dealt
                # length class is not checkpointed, so the scenario stays
                # pending and the next call retries it (same policy as any
                # unusable draft — failed work is never paid for twice).
                lc = scen_by_pid[x["scenario_id"]].get("length_class")
                if not compose_scenarios.length_ok(str(x["prompt"]), lc):
                    length_rejects += 1
                    print(f"    {x['scenario_id']}: draft is {len(str(x['prompt']).strip())} chars, "
                          f"far off its dealt length class ({lc}) — will retry.")
                    continue
                by_pid[x["scenario_id"]] = x
        if not by_pid and length_rejects:
            # Every draft parsed but missed its length band: a real retry case,
            # not a parse failure — don't count it toward the 3-strike limit.
            continue
        if not by_pid:
            consecutive_failures += 1
            # Keep the raw — it cost a call, and a discarded raw is an
            # undiagnosable failure (same policy as 2a's scope_failures.jsonl).
            utils.append_jsonl({"batch": batch_no, "attempt": consecutive_failures,
                                "raw": raw}, output_dir / "draft_failures.jsonl")
            print(f"    Batch {batch_no} unusable (parse/shape failure) — retrying with a fresh call "
                  f"(raw kept in draft_failures.jsonl).")
            if consecutive_failures >= 3:
                raise SystemExit("Three consecutive unusable batches — inspect "
                                 f"{output_dir / 'draft_failures.jsonl'} and the template.")
            continue
        consecutive_failures = 0
        utils.append_jsonl({"batch": batch_no, "requested": len(batch),
                            "scenario_ids": sorted(batch_pids),
                            "scenarios_block": scenarios_block}, batches_path)

        # --- Step 1c (optional): rewrite each prompt text; annotation unchanged.
        # Refine calls fan out across the batch (API call + parse only, per the
        # parallel_map contract); record assembly below stays serial on the main
        # thread so ID assignment and file writes keep input order.
        refined_by_pid: dict[str, dict | None] = {}
        if refine_enabled:
            to_refine = [(p, by_pid[p["scenario_id"]]) for p in batch
                         if by_pid.get(p["scenario_id"]) is not None]

            def _refine(pair: tuple) -> tuple[dict | None, list[dict]]:
                scenario, draft = pair
                print(f"    [1c] Refining {scenario['scenario_id']}...")
                return refine_draft(scenario, draft, prompts_dir,
                                    model=config["dad"].get("prompt_refine_model"))

            workers = int(config.get("workers", 1))
            for (scenario, _), (refined, failures) in zip(
                    to_refine, utils.parallel_map(_refine, to_refine, workers)):
                refined_by_pid[scenario["scenario_id"]] = refined
                # Workers only call + parse; failure raws persist here on the
                # main thread, in input order (the parallel_map contract).
                for f in failures:
                    utils.append_jsonl(f, output_dir / "refine_failures.jsonl")

        for p in batch:
            pid = p["scenario_id"]
            draft = by_pid.get(pid)
            if draft is None:
                print(f"    {pid}: missing from the batch output — will retry.")
                continue

            ann = _normalize_annotation(draft["annotation"])

            user_message = str(draft["prompt"]).strip()
            refine_notes = None
            refine_failed = False
            if refine_enabled:
                refined = refined_by_pid.get(pid)
                if refined is not None:
                    user_message, refine_notes = refined["prompt"], refined["notes"]
                else:
                    # The load-bearing rewrite didn't happen: ship the 1b draft,
                    # but stamp the record so the viewer (and any later audit)
                    # can see which prompts skipped the 1c pass.
                    refine_failed = True
                    print(f"    {pid}: refine unusable after {MAX_REFINE_ATTEMPTS} attempts "
                          "— keeping the 1b draft (refine_failed stamped, raws in "
                          "refine_failures.jsonl).")

            record = {
                "prompt_id": _next_id(examples, id_start),
                "prompt_gid": f"P-{registry.assign('prompt', prompt_fingerprint(user_message)):04d}",
                "user_message": user_message,
                "annotation": ann,
                "source": "generated",
                "batch": batch_no,
                "scenario_id": pid,
                "scenario_gid": p.get("scenario_gid"),
                # denormalized from the scenario so the checklist can read taxa /
                # AI-systems coverage exactly, without keyword-scanning the text
                "taxa_category": p["taxa_category"],
                "taxa_subcategory": p.get("taxa_subcategory"),
                "frontier_frame": p.get("frontier_frame"),
                "length_class": p.get("length_class"),
                "cultural_setting": p.get("cultural_setting"),
            }
            if refine_failed:
                record["refine_failed"] = True
            if refine_notes is not None:
                # keep the 1b draft alongside the 1c-refined prompt for inspection
                record["draft_user_message"] = str(draft["prompt"]).strip()
                record["refine_notes"] = refine_notes
                utils.append_jsonl({
                    "scenario_id": pid,
                    "draft_prompt": str(draft["prompt"]).strip(),
                    "refined_prompt": user_message,
                    "notes": refine_notes,
                }, refinements_path)
            examples.append(record)
            accepted.add(pid)
            utils.append_jsonl(record, output_path)
        registry.save()

    print(f"  {len(examples)} dilemma prompts in {output_path}")
    print_checklist(examples, save_path=output_dir / "checklist.txt")
    return examples
