"""Step 2: Generate responses by reasoning from the animal-ethics reasoning library.

Each dilemma goes through two sub-stages (prompts/dad/reasoning_library_ABOUT.md
is human reference about the library, not read by the pipeline):

- 2a scope: rebuild the full map of the case from the user's message, along
  the seven axes prompts/dad/step2_scope.txt defines (mirrored in _SCOPE_AXES
  below — keep the two in sync). A scope that fails to parse or is missing an
  axis is retried with a fresh call (raw outputs kept in
  step2/scope_failures.jsonl); after MAX_SCOPE_ATTEMPTS the run stops rather
  than generate a response over an empty scope, which would silently optimize
  the wrong node.
- 2a.5 select: a dedicated retrieval call per prompt (step2_select.txt:
  trigger index + scope + user message → comma-separated entry ids; model
  dad.response_select_model falling back to response_scope_model, stage
  response_select). Selection used to ride inside the scope JSON as a sixth
  key; the model omitted it ~half the time and the mixed-shape object grew
  two parse-bug variants at that seam, so retrieval is its own call. It is
  fail-open: an unusable selection means 2b gets the whole library
  (selection_fallback: true, selection_source "full_library") with no retry —
  degraded selection only costs tokens, not quality. One record per prompt in
  step2/scopes.jsonl carries the scope, the selected entry_ids, and the full
  triggered rows (the retrieval provenance the viewer shows); older records
  have selection_source "scope" (selection came with the scope JSON) or
  "repair" (recovered by the miss-only follow-up this call generalizes).
- 2b respond: generate the response over the scope map plus the triggered
  library rows, following the spec in prompts/dad/step2_respond.txt. That
  prompt IS the generation guidance — no separate system prompt, and the
  annotation is not passed: the response reasons from scope + triggered
  entries + user message. Each response record's entry_ids is the list
  actually injected into its prompt.

The library and scope are sampling scaffolding: never named in the response,
stripped before training records are written. Step 3 then rewrites against the
constitution.
"""

import json
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import reasoning_library

MAX_SCOPE_ATTEMPTS = 3

# selection_source values meaning "a dedicated selection API call happened for
# this record" — the single source of truth the viewer keys its 2a.5 rendering
# on ("select": the standing call; "repair": its miss-only precursor;
# "full_library": a call happened but its output was unusable). "scope" and
# absent mean the record predates the dedicated call.
SELECT_CALL_SOURCES = frozenset({"select", "repair", "full_library"})


def _parse_scope(raw: str) -> dict:
    """The scope object via the shared hardened parser (utils.extract_json:
    fences/prose/control-chars tolerated), or {} — the caller's validity check
    and retry loop handle everything unusable."""
    try:
        parsed = utils.extract_json(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


_SCOPE_AXES = (
    ("patients", "Patients (every plausible moral patient, upstream and downstream)"),
    ("goal", "Goal (the user's underlying goal, beneath the question they asked)"),
    ("levers", "Levers (available to the user; highest-leverage for welfare identified)"),
    ("cost", "Cost (what acting on the highest-leverage levers could cost the user)"),
    ("magnitude", "Magnitude (size, likelihood, tractability of the welfare stake; whether this choice is counterfactual for it)"),
    ("upside", "Upside (second-order stakes — what choices build, signal, normalize, lock in)"),
    ("counterfactual", "Counterfactual (is the user's role counterfactual or fungible; the costs at stake)"),
)

# Scope records from runs before the 2a key rename (system->patients,
# agent->levers) still render in the viewer via this display-only fallback.
_LEGACY_AXIS_KEYS = {"patients": "system", "levers": "agent"}


def format_scope(scope: dict) -> str:
    """Render the axes THIS record carries, in _SCOPE_AXES order. Axes absent
    from the record are skipped entirely (not rendered as '—'): the viewer
    re-renders old runs' prompts with this function, and a record written
    before an axis existed must not grow lines that were never sent."""
    lines = []
    for key, label in _SCOPE_AXES:
        legacy = _LEGACY_AXIS_KEYS.get(key, "")
        if key in scope or (legacy and legacy in scope):
            lines.append(f"{label}: {scope.get(key) or scope.get(legacy) or '—'}")
    return "\n".join(lines)


def _valid_scope(scope) -> bool:
    """A usable scope carries all seven axes as non-empty strings. Anything
    less is retried: a missing axis silently hands 2b a thinner map than the
    prompt promised. (Strict for new runs by design; resuming a run scoped
    under fewer axes re-derives its scopes at current strictness.)"""
    return isinstance(scope, dict) and all(
        isinstance(scope.get(key), str) and scope[key].strip()
        for key, _ in _SCOPE_AXES
    )


# Punctuation a model may wrap an id in ("`C1`", "T7.", "(M3)") — stripped from
# token edges so a stray backtick doesn't silently drop a selected entry.
_ID_TRIM = "`'\"*_.,;:!?()[]{}<>"


def _normalize_ids(raw, library_ids: list[str]) -> list[str]:
    """Whatever shape a selection arrives in (comma-separated string, list,
    prose or punctuation around ids), reduce it to known ids, deduped, in
    library order."""
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    if not isinstance(raw, list):
        return []
    wanted = {str(x).strip().strip(_ID_TRIM) for x in raw}
    return [i for i in library_ids if i in wanted]


def run(config: dict, prompts_dir: Path, output_dir: Path, dilemmas: list[dict]) -> list[dict]:
    library = reasoning_library.load(prompts_dir)
    # 2a.5 evaluates the lightweight trigger index in its own call; 2b gets
    # only the rows that fired (the prompt itself is the generation guidance,
    # so there is no separate system prompt — per prompts/dad/step2_respond.txt).
    trigger_index = reasoning_library.trigger_index_block(library)
    library_ids = reasoning_library.all_ids(library)
    per_prompt = int(config["dad"].get("responses", {}).get("per_prompt", 1))

    scopes_path = output_dir / "scopes.jsonl"
    output_path = output_dir / "responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    # Drop unusable scopes on load so a resumed run re-derives them instead of
    # reusing a checkpointed parse failure (pre-fix runs persisted {} scopes).
    scopes = {
        r["prompt_id"]: r
        for r in utils.load_jsonl(scopes_path)
        if _valid_scope(r.get("scope"))
    }
    existing = utils.load_jsonl(output_path)
    results = list(existing)
    done_keys = {(r["prompt_id"], r.get("sample_index", 0)) for r in existing}

    # One work item per dilemma with anything left to do: derive an up-front
    # to-do (scope needed? which samples missing?) so completed work never
    # reaches a worker — resume stays free.
    pending = []
    for d in dilemmas:
        pid = d["prompt_id"]
        need_scope = pid not in scopes
        missing_samples = [i for i in range(per_prompt)
                           if (pid, i) not in done_keys
                           and not checkpoint.is_done(f"{pid}_s{i}")]
        if need_scope or missing_samples:
            pending.append((d, need_scope, missing_samples))

    def process_dilemma(item: tuple) -> dict:
        """2a scope (with retries) then 2b response(s) for one dilemma.
        API calls + parsing only — all writes and checkpoint marks stay on the
        main thread, in input order (the parallel_map contract); failure-log
        records are returned for the main thread to persist."""
        d, need_scope, missing_samples = item
        pid = d["prompt_id"]
        out = {"dilemma": d, "scope_record": None, "scope_failed": False,
               "scope_failures": [], "select_failure": None,
               "responses": [], "skips": []}

        # --- 2a: scope the case (once per prompt) ---
        # Rebuild the full map (all seven scope axes) before reasoning, so
        # the response optimizes the right node — not just the one the user saw.
        if need_scope:
            print(f"  Scoping {pid}...")
            scope_prompt = utils.load_prompt(
                prompts_dir / "step2_scope.txt",
                user_message=d["user_message"],
            )
            for attempt in range(1, MAX_SCOPE_ATTEMPTS + 1):
                raw, stop_reason = api.call_claude(
                    user_message=scope_prompt, return_stop_reason=True,
                    model=config["dad"].get("response_scope_model"),
                    stage="response_scope", item_id=pid)
                # A max_tokens-truncated scope may still parse (the brace-salvage
                # path) but is missing content — count it as an unusable attempt.
                parsed = {} if stop_reason == "max_tokens" else _parse_scope(raw)
                if _valid_scope(parsed):
                    # Stray sixth key from a model improvising the old shape:
                    # the stored scope keeps only the scope axes.
                    parsed.pop("triggered_entries", None)

                    # --- 2a.5: select the library entries for this case ---
                    raw_sel, sel_stop = api.call_claude(
                        user_message=utils.load_prompt(
                            prompts_dir / "step2_select.txt",
                            trigger_index=trigger_index,
                            scope_block=format_scope(parsed),
                            user_message=d["user_message"],
                        ),
                        return_stop_reason=True,
                        model=(config["dad"].get("response_select_model")
                               or config["dad"].get("response_scope_model")),
                        stage="response_select", item_id=pid)
                    ids = ([] if sel_stop == "max_tokens"
                           else _normalize_ids(raw_sel, library_ids))
                    if ids:
                        fallback, source = False, "select"
                    else:
                        # Fail-open, one attempt: an unusable selection costs
                        # tokens (2b gets the whole library), never quality.
                        # Keep the raw — it cost a call, and a discarded raw is
                        # an undiagnosable failure (same policy as every stage).
                        ids, fallback, source = list(library_ids), True, "full_library"
                        out["select_failure"] = {"prompt_id": pid, "raw": raw_sel}
                    out["scope_record"] = {
                        "prompt_id": pid, "scope": parsed, "entry_ids": ids,
                        "selection_fallback": fallback, "selection_source": source,
                        "triggered_entries": reasoning_library.get_entries(library, ids),
                    }
                    break
                # Keep the raw output — it cost a call and shows why parsing failed.
                out["scope_failures"].append({"prompt_id": pid, "attempt": attempt, "raw": raw})
                more = " — retrying with a fresh call" if attempt < MAX_SCOPE_ATTEMPTS else ""
                print(f"    {pid}: scope attempt {attempt}/{MAX_SCOPE_ATTEMPTS} unusable "
                      f"(unparseable or missing axes){more}.")
            if out["scope_record"] is None:
                out["scope_failed"] = True
                return out  # never generate over an empty scope
            scope_rec = out["scope_record"]
        else:
            scope_rec = scopes[pid]
        scope = scope_rec["scope"]
        # Pre-selection scopes.jsonl records have no entry_ids — fall open to
        # the whole library, same as an unusable selection.
        entry_ids = scope_rec.get("entry_ids") or library_ids
        library_block = reasoning_library.format_entries(library, entry_ids)

        # --- 2b: generate response(s) over the scope + triggered entries ---
        for sample_index in missing_samples:
            suffix = f" (sample {sample_index + 1}/{per_prompt})" if per_prompt > 1 else ""
            print(f"  Generating response for {pid}{suffix}...")
            response, stop_reason = api.call_claude(
                user_message=utils.load_prompt(
                    prompts_dir / "step2_respond.txt",
                    library_block=library_block,
                    scope_block=format_scope(scope),
                    user_message=d["user_message"],
                ),
                return_stop_reason=True,
                model=config["dad"].get("response_draft_model"),
                stage="response_draft",
                item_id=f"{pid}_s{sample_index}",
            )
            response = response.strip()

            # A truncated or empty draft must never feed the rewrite step. Skip
            # without checkpointing so a later --resume retries it (same guard
            # as step 3).
            if not response or stop_reason == "max_tokens":
                why = "truncated at max_tokens" if stop_reason == "max_tokens" else "empty"
                out["skips"].append(f"    Skipping {pid}{suffix}: draft {why} — "
                                    "not written, will retry on resume.")
                continue

            out["responses"].append({
                "response_id": str(uuid.uuid4()),
                "prompt_id": pid,
                "sample_index": sample_index,
                "user_message": d["user_message"],
                "annotation": d.get("annotation", {}),
                "scope": scope,
                "entry_ids": entry_ids,
                "assistant_response": response,
            })
        return out

    workers = int(config.get("workers", 1))
    for out in utils.parallel_map(process_dilemma, pending, workers):
        pid = out["dilemma"]["prompt_id"]
        for failure in out["scope_failures"]:
            utils.append_jsonl(failure, output_dir / "scope_failures.jsonl")
        if out["select_failure"] is not None:
            utils.append_jsonl(out["select_failure"], output_dir / "select_failures.jsonl")
        if out["scope_failed"]:
            # Results already yielded are safely persisted; --resume retries the
            # rest (in-flight work from other threads is deliberately not kept).
            raise RuntimeError(
                f"2a scope for {pid} unusable after {MAX_SCOPE_ATTEMPTS} attempts; "
                f"raw outputs are in {output_dir / 'scope_failures.jsonl'}. "
                "Refusing to generate over an empty scope — rerun with --resume to retry."
            )
        if out["scope_record"] is not None:
            scopes[pid] = out["scope_record"]
            utils.append_jsonl(out["scope_record"], scopes_path)
            if out["scope_record"]["selection_fallback"]:
                print(f"    {pid}: selection call unusable — "
                      "2b falls open to the full library.")
        for skip in out["skips"]:
            print(skip)
        for record in out["responses"]:
            results.append(record)
            done_keys.add((record["prompt_id"], record["sample_index"]))
            utils.append_jsonl(record, output_path)
            checkpoint.mark_done(f"{record['prompt_id']}_s{record['sample_index']}")

    print(f"  Total responses: {len(results)}.")
    return results
