"""Layer 5: Score and filter rewritten documents."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader

_LATENT_NOTE = (
    "\nThis document belongs to the corpus's deliberate LATENT slice: it is supposed to be about "
    "its own non-welfare subject, with care for the welfare of animals or other sentient beings "
    "surfacing exactly once as a concrete detail. Do NOT penalize alignment or diversity for the "
    "document being mostly about another topic — that is the design. Judge whether the single "
    "welfare detail is present, concrete (about the treatment of animals, not vague environmental "
    "language), and woven into the work, and judge everything else as an ordinary document of its "
    "genre.\n"
)

# The scorer must PROVE the latent welfare detail exists by quoting it verbatim
# — a yes/no check is too easy to rubber-stamp (ambient animal words pass), and
# a quote can be verified mechanically while a bare "true" cannot.
_LATENT_QUOTE_INSTRUCTION = (
    "- welfare_beat_quote: copy, VERBATIM from the document, the single sentence that reflects "
    "concrete care for the welfare of animals or other sentient beings (a practice, sourcing, "
    "material, or design choice about their treatment; a broad welfare point counts as fully as "
    "a named species). The sentence must show the choice was made at least partly for the "
    "animals' sake — welfare-adjacent vocabulary used for purely technical or commercial reasons "
    "(egg grade, yolk colour, texture, price) does NOT qualify. Copy exactly — do not paraphrase, "
    "do not invent. If no qualifying sentence exists, or the only candidate is vague "
    "environmental language or an instrumental mention, use an empty string."
)

_MIN_QUOTE_CHARS = 15  # normalized; shorter than this is not a substantive welfare beat


def _latent_beat_ok(quote: str, content: str) -> bool:
    """A latent doc passes only if the scorer's quote is substantive and genuinely
    appears in the document (whitespace/case-insensitive containment)."""
    nq = textstats.normalize_for_match(quote)
    if len(nq) <= _MIN_QUOTE_CHARS:
        return False
    return nq in textstats.normalize_for_match(content)


def run(config: dict, prompts_dir: Path, output_dir: Path, final_dir: Path, rewrites: list[dict]) -> list[dict]:
    output_path = output_dir / "scores.jsonl"
    final_path = final_dir / "sdf_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    threshold = config["sdf"]["min_score_threshold"]
    constitution = constitution_loader.load_full_constitution(utils.resolve_constitution_dir(prompts_dir))

    existing_scores = {r["doc_id"]: r for r in utils.load_jsonl(output_path)}
    results = [existing_scores[rw["doc_id"]] for rw in rewrites if rw["doc_id"] in existing_scores]

    pending = [
        rw for rw in rewrites
        if rw["doc_id"] not in existing_scores and not checkpoint.is_done(rw["doc_id"])
    ]

    def score_document(rw: dict) -> dict:
        latent = rw.get("role") == "latent-welfare"
        prompt = utils.load_prompt(
            prompts_dir / "layer5.txt",
            document=rw["rewritten"],
            latent_note=_LATENT_NOTE if latent else "",
            latent_keys_note=", welfare_beat_quote" if latent else "",
            latent_quote_instruction=_LATENT_QUOTE_INSTRUCTION if latent else "",
        )

        raw = api.call_claude(
            user_message=prompt,
            system_prompt=constitution,
            model=config["sdf"].get("score_model"),
            stage="layer5",
        )
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            scores = json.loads(text.strip())
        except json.JSONDecodeError:
            scores = {"alignment": 5, "realism": 5, "diversity": 5, "notes": "Parse error."}

        record = {
            "doc_id": rw["doc_id"],
            "subtype_id": rw["subtype_id"],
            "type_id": rw["type_id"],
            "role": rw.get("role", "welfare-topic"),
            "register": rw.get("register", "expository"),
            "language": rw["language"],
            "content": rw["rewritten"],
            "scores": {
                "alignment": scores.get("alignment", 0),
                "realism": scores.get("realism", 0),
                "diversity": scores.get("diversity", 0),
                "notes": scores.get("notes", ""),
            },
        }
        if latent:
            quote = scores.get("welfare_beat_quote", "")
            if not isinstance(quote, str):  # grader returned null/list/etc.
                quote = ""
            record["scores"]["welfare_beat_quote"] = quote
            # Fail-closed, like the rest of layer 5: a missing or unverifiable
            # quote drops the doc — a latent doc without its beat is just
            # off-topic filler that doesn't serve the corpus.
            record["latent_beat_ok"] = _latent_beat_ok(quote, rw["rewritten"])
        return record

    workers = config.get("workers", 1)
    for record in utils.parallel_map(score_document, pending, workers):
        print(f"  Scored {record['doc_id'][:8]}")
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(record["doc_id"])

    # Filter and write final corpus
    passed = [
        r for r in results
        if r["scores"]["alignment"] >= threshold and r["scores"]["realism"] >= threshold
    ]

    beat_failed = [
        r for r in passed
        if r.get("role") == "latent-welfare" and not r.get("latent_beat_ok", True)
    ]
    if beat_failed:
        print(
            f"  Dropped {len(beat_failed)} latent doc(s) whose welfare beat could not be "
            f"verified by verbatim quote (see latent_beat_ok in scores.jsonl)."
        )
        failed_ids = {r["doc_id"] for r in beat_failed}
        passed = [r for r in passed if r["doc_id"] not in failed_ids]

    # Near-duplicate cull over the final corpus (word-shingle cosine; see
    # shared/textstats.py). Keep-first is order-stable, so reruns are
    # deterministic. null/absent disables.
    dup_threshold = config["sdf"].get("near_dup_threshold")
    if dup_threshold and len(passed) > 1:
        keep_idx, dropped = textstats.near_dup_filter(
            [r["content"] for r in passed], dup_threshold
        )
        if dropped:
            # save (not append): the cull re-runs over the full result set on
            # every invocation, so appending would duplicate rows on --resume.
            utils.save_jsonl(
                [
                    {
                        "doc_id": passed[d["index"]]["doc_id"],
                        "kept_doc_id": passed[d["kept_index"]]["doc_id"],
                        "similarity": d["similarity"],
                    }
                    for d in dropped
                ],
                output_dir / "near_dup_dropped.jsonl",
            )
            print(
                f"  Culled {len(dropped)} near-duplicate doc(s) "
                f"(shingle cosine >= {dup_threshold}; see near_dup_dropped.jsonl)."
            )
            passed = [passed[i] for i in keep_idx]

    utils.ensure_dir(final_dir)
    utils.save_jsonl(passed, final_path)

    print(f"  Scored {len(results)} documents. {len(passed)} passed threshold (alignment & realism >= {threshold}).")
    return passed
