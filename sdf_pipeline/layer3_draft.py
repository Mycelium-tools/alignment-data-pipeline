"""Layer 3: Generate document drafts for each subtype."""

import random
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader
from sdf_pipeline import composition

_DOC_TAG_RE = re.compile(r"<document>(.*?)</document>", re.DOTALL)
# Models occasionally double the opening tag; the non-greedy capture then keeps
# the inner "<document>" as content — which contaminated final training text in
# two consecutive audited runs. Strip any stray tags at the extracted edges.
_STRAY_TAG_RE = re.compile(r"^(?:\s*</?document>\s*)+|(?:\s*</?document>\s*)+$")

# Cross-call state for the avoid-note: person-ish names ("Wren Halvorsen-Tate"),
# and spelled-out or numeric quantities that both audits found repeating across
# supposedly independent documents ("thirty-one years" twice, "47 replies").
_NAME_RE = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?\b")
_NUMBER_PHRASE_RE = re.compile(
    r"\b(?:\w+[-\s])?(?:\d+|twenty|thirty|forty|fifty)[-\s]?\w*\s+"
    r"(?:years?|replies|birds|head|animals|miles)\b", re.IGNORECASE)


def _avoid_note(prior_drafts: list[dict], rng: random.Random) -> str:
    """Cross-call state: sample names, openings, and distinctive quantities from
    drafts already written, so parallel calls stop converging on the same
    furniture (the template-twinning both corpus audits flagged). Empty on the
    first wave of a fresh run."""
    if not prior_drafts:
        return ""
    sample = rng.sample(prior_drafts, min(10, len(prior_drafts)))
    names, numbers = set(), set()
    openings = []
    for d in sample:
        text = d["content"]
        names.update(_NAME_RE.findall(text)[:6])
        numbers.update(m.strip() for m in _NUMBER_PHRASE_RE.findall(text)[:4])
        openings.append(text[:70].replace("\n", " ").strip())
    lines = []
    if names:
        lines.append("- character/person names: " + "; ".join(sorted(names)[:15]))
    if openings:
        lines.append("- opening lines: " + " | ".join(openings[:6]))
    if numbers:
        lines.append("- specific quantities: " + "; ".join(sorted(numbers)[:10]))
    return (
        "\nDocuments already written for this corpus used the following. Do NOT "
        "reuse or closely echo any of them — different names, a different opening "
        "move, different specific numbers:\n" + "\n".join(lines) + "\n"
    )


def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    # Two distinct injections: the REAL constitution is the quotable artifact;
    # the principles block is the invisible welfare lens (never a document in
    # the depicted world).
    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    constitution = constitution_loader.load_constitution_claude(constitution_dir)
    principles = constitution_loader.load_welfare_principles_block(constitution_dir)
    try:
        principle_rows = constitution_loader.load_principles(constitution_dir)
    except FileNotFoundError:
        principle_rows = constitution_loader.load_principles()
    principles_by_number = {
        int(p["number"]): p["principle"].strip() for p in principle_rows if p.get("number")
    }

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [st for st in subtypes if not checkpoint.is_done(st["subtype_id"])]

    def draft_documents(st: dict, avoid_note: str = "") -> list[dict]:
        # The TCW template takes the subtype as a single {subtype} block; compose
        # it from the layer-1/2 record plus its composition-axis assignment.
        subtype_block = (
            f"Document type: {st['type_name']}\n"
            f"Subtype: {st['subtype_name']}\n"
            f"Specification: {st['description']}\n"
            f"Tone: {st['tone']}"
        )
        assignment = composition.render_assignment(st, principles_by_number)
        if assignment:
            subtype_block += "\n\n" + assignment

        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            subtype=subtype_block,
            CONSTITUTION=constitution,
            PRINCIPLES=principles,
            avoid_note=avoid_note,
        )

        raw = api.call_claude(
            user_message=prompt, max_tokens=8000, model=config["sdf"].get("draft_model"),
            stage="layer3",
        )

        # Extract <document>...</document> blocks; fall back to the whole output
        # if untagged. A closed tag implies a complete document; the untagged
        # fallback may be a token-capped cutoff, so trim it back to the last
        # complete sentence — a mid-sentence ending is itself a training
        # artifact. Trailing separator-only lines (a bare closing ---) are
        # stripped from every doc.
        docs = [
            textstats.strip_trailing_separators(_STRAY_TAG_RE.sub("", m).strip())
            for m in _DOC_TAG_RE.findall(raw)
            if m.strip()
        ]
        docs = [d for d in docs if d]
        if not docs:
            fallback = re.sub(r"<angles>.*?(?:</angles>|\Z)", "", raw, flags=re.DOTALL).strip()
            fallback = _STRAY_TAG_RE.sub("", fallback).strip()
            fallback = textstats.trim_unfinished(textstats.strip_trailing_separators(fallback))
            if fallback:
                docs = [fallback]

        return [
            {
                "doc_id": str(uuid.uuid4()),
                "subtype_id": st["subtype_id"],
                "type_id": st["type_id"],
                "language": st["language"],
                "content": doc_text,
            }
            for doc_text in docs
        ]

    # Waves (same pattern as layer 2): subtypes within a wave run in parallel;
    # between waves the avoid-note is refreshed from every draft written so
    # far, so later calls see earlier output. Wave size = workers, so this adds
    # no wall-clock over plain parallel_map on a single-wave run.
    workers = config.get("workers", 1)
    wave_size = max(workers, 1)
    for wave_start in range(0, len(pending), wave_size):
        wave = pending[wave_start : wave_start + wave_size]
        note = _avoid_note(results, random.Random(f"layer3-avoid:{wave_start}"))
        for st, records in zip(
            wave, utils.parallel_map(lambda st: draft_documents(st, note), wave, workers)
        ):
            print(f"  Drafted {len(records)} docs for subtype: {st['subtype_name'][:60]}")
            for record in records:
                results.append(record)
                utils.append_jsonl(record, output_path)
            checkpoint.mark_done(st["subtype_id"])

    print(f"  Total drafts: {len(results)}")
    return results
