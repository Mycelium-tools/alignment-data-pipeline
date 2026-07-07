"""Step 2: Generate responses by reasoning from the animal-ethics reasoning library.

Each dilemma goes through two sub-stages (prompts/dad/reasoning_library_ABOUT.md
is human reference about the library, not read by the pipeline):

- 2a scope: rebuild the full map before reasoning — the whole harm pathway and
  every moral patient (system), the highest-leverage lever from the user's seat
  (agent), what acting honestly costs this person (cost), the second-order
  effect worth aiming at (upside), and the realistic baseline if the user does
  nothing (counterfactual). Reads everything from the user's message. One record per
  prompt in step2/scopes.jsonl. A scope that fails to parse or is missing an
  axis is retried with a fresh call (raw outputs kept in
  step2/scope_failures.jsonl); after MAX_SCOPE_ATTEMPTS the run stops rather
  than generate a response over an empty scope, which would silently optimize
  the wrong node.
- 2b respond: generate the response over the scope map. The whole library
  (conduct C*, core moves M*, topic T*) is embedded in the response prompt
  itself, which IS the generation guidance — so there is no separate system
  prompt. The annotation is not passed and calibration direction is not named
  here: the response reasons from scope + library + user message, from the
  ethics of the case rather than the user's leaning. See
  prompts/dad/step2_respond.txt (the response-generation spec).

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


def _parse_scope(raw: str) -> dict:
    # strict=False accepts literal newlines/tabs inside string values — the way
    # a prose-heavy JSON object at temperature 1.0 most often goes invalid.
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip(), strict=False)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e <= s:
            return {}
        try:
            parsed = json.loads(text[s:e + 1], strict=False)
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


_SCOPE_AXES = (
    ("system", "System (full harm pathway + every moral patient + displacement check)"),
    ("agent", "Agent (highest-leverage lever available from the user's seat)"),
    ("cost", "Cost (what acting honestly costs this person)"),
    ("upside", "Upside (second-order effect worth aiming at)"),
    ("counterfactual", "Counterfactual (what happens if the user doesn't do it — the realistic baseline)"),
)


def format_scope(scope: dict) -> str:
    return "\n".join(f"{label}: {scope.get(key) or '—'}" for key, label in _SCOPE_AXES)


def _valid_scope(scope) -> bool:
    """A usable scope carries all five axes as non-empty strings. Anything less
    renders as '—' lines in the 2b prompt, which tells the response model the
    case 'is already scoped' while handing it nothing."""
    return isinstance(scope, dict) and all(
        isinstance(scope.get(key), str) and scope[key].strip()
        for key, _ in _SCOPE_AXES
    )


def run(config: dict, prompts_dir: Path, output_dir: Path, dilemmas: list[dict]) -> list[dict]:
    library = reasoning_library.load(prompts_dir)
    # The whole library (conduct C*, core moves M*, topic T*) goes into the
    # response prompt; the prompt itself is the generation guidance, so there is
    # no separate system prompt (per prompts/dad/step2_respond.txt).
    library_block = reasoning_library.format_library(library)
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

    for d in dilemmas:
        pid = d["prompt_id"]

        # --- 2a: scope the case (once per prompt) ---
        # Rebuild the full map (system, agent, cost, upside, counterfactual) before reasoning, so
        # the response optimizes the right node — not just the one the user saw.
        if pid not in scopes:
            print(f"  Scoping {pid}...")
            scope_prompt = utils.load_prompt(
                prompts_dir / "step2_scope.txt",
                user_message=d["user_message"],
            )
            record = None
            for attempt in range(1, MAX_SCOPE_ATTEMPTS + 1):
                raw, stop_reason = api.call_claude(
                    user_message=scope_prompt, return_stop_reason=True)
                # A max_tokens-truncated scope may still parse (the brace-salvage
                # path) but is missing content — count it as an unusable attempt.
                parsed = {} if stop_reason == "max_tokens" else _parse_scope(raw)
                if _valid_scope(parsed):
                    record = {"prompt_id": pid, "scope": parsed}
                    break
                # Keep the raw output — it cost a call and shows why parsing failed.
                utils.append_jsonl(
                    {"prompt_id": pid, "attempt": attempt, "raw": raw},
                    output_dir / "scope_failures.jsonl",
                )
                more = " — retrying with a fresh call" if attempt < MAX_SCOPE_ATTEMPTS else ""
                print(f"    {pid}: scope attempt {attempt}/{MAX_SCOPE_ATTEMPTS} unusable "
                      f"(unparseable or missing axes){more}.")
            if record is None:
                raise RuntimeError(
                    f"2a scope for {pid} unusable after {MAX_SCOPE_ATTEMPTS} attempts; "
                    f"raw outputs are in {output_dir / 'scope_failures.jsonl'}. "
                    "Refusing to generate over an empty scope — rerun with --resume to retry."
                )
            scopes[pid] = record
            utils.append_jsonl(record, scopes_path)
        scope = scopes[pid]["scope"]

        # --- 2b: generate response(s) over the scope + full library ---
        for sample_index in range(per_prompt):
            ck = f"{pid}_s{sample_index}"
            if (pid, sample_index) in done_keys or checkpoint.is_done(ck):
                continue

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
            )
            response = response.strip()

            # A truncated or empty draft must never feed the rewrite step. Skip
            # without checkpointing so a later --resume retries it (same guard
            # as step 3).
            if not response or stop_reason == "max_tokens":
                why = "truncated at max_tokens" if stop_reason == "max_tokens" else "empty"
                print(f"    Skipping {pid}{suffix}: draft {why} — not written, will retry on resume.")
                continue

            record = {
                "response_id": str(uuid.uuid4()),
                "prompt_id": pid,
                "sample_index": sample_index,
                "user_message": d["user_message"],
                "annotation": d.get("annotation", {}),
                "scope": scope,
                "entry_ids": library_ids,
                "assistant_response": response,
            }
            results.append(record)
            done_keys.add((pid, sample_index))
            utils.append_jsonl(record, output_path)
            checkpoint.mark_done(ck)

    print(f"  Total responses: {len(results)}.")
    return results
