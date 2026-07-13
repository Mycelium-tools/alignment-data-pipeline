"""Layer 3: Generate document drafts for each subtype."""

import random
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, entity_pools, textstats, utils, constitution_loader

_DOC_TAG_RE = re.compile(r"<document>(.*?)</document>", re.DOTALL)


def _strip_stray_doc_tags(text: str) -> str:
    """Remove leftover <document> tags from extracted content (a doubled
    opening tag leaves one inside the non-greedy match)."""
    text = re.sub(r"^(?:\s*<document>)+\s*", "", text)
    return re.sub(r"\s*(?:</document>\s*)+$", "", text)

# Per-document samples handed to the drafting prompt. Small on purpose: the
# pools exist to break name collapse, not to make every document name-dense.
_NAMES_PER_DOC = 4
_ORGS_PER_DOC = 3

# Rhetorical-shape menu seeded into the STAGE-1 brainstorm (a few sampled per
# subtype), so shape variety doesn't rely on the model reinventing it each
# call. Adapted from the CAML notebook's STRUCTURES axis, minus its "a skeptic
# gradually convinced by evidence" entry — that is the conversion arc the
# preamble bans.
STRUCTURE_HINTS = [
    "a first-person field narrative",
    "a historical account of how practice changed",
    "a concrete case study of one organisation",
    "a terse data-and-methods report",
    "a Q&A or interview transcript",
    "a personal reflective essay",
    "a comparison of two competing approaches",
    "a practitioner how-we-did-it walkthrough",
    "a forward-looking scenario",
    "a problem diagnosis without a tidy solution",
    "a profile of the people involved",
    "an exchange of letters or messages",
]
_HINTS_PER_DOC = 4

# Per-role craft guidance injected under the brief block — how to write an
# ai-character document vs. a constitution discussion vs. a background-world
# piece. Lives in prompts/sdf/role_*.txt so it snapshots with the run.
_ROLE_GUIDANCE_FILES = {
    "ai-character": "role_ai_character.txt",
    "constitution-identity": "role_constitution_identity.txt",
    "welfare-topic": "role_welfare_topic.txt",
}


def _load_role_guidance(prompts_dir: Path) -> dict[str, str]:
    """Load the per-role guidance blocks, falling back to the repo's live
    copies for run snapshots that predate the files."""
    live_dir = Path(__file__).parent.parent / "prompts" / "sdf"
    guidance = {}
    for role, name in _ROLE_GUIDANCE_FILES.items():
        path = prompts_dir / name
        if not path.exists():
            path = live_dir / name
        guidance[role] = utils.load_prompt(path)
    return guidance


_REGISTER_NOTES = {
    "first-person": (
        "Voice: this is a first-person genre — write in a distinct, informal, conversational "
        "voice, the way a real person actually writes a {genre}: contractions, everyday words, "
        "varied sentence lengths, personality, the occasional aside. Do not slip into a measured, "
        "hedged, institutional register or abstract nominalizations. Stay on the subject — the "
        "author's life may color the writing but is not the topic."
    ),
    "expository": (
        "Voice: write in the authentic professional register of a real {genre} — measured, "
        "third-person where the genre expects it, with the vocabulary a working editor of that "
        "genre would accept. Professional does not mean AI-glossy: real trade and policy writing "
        "has texture, specifics, and occasional bluntness."
    ),
}

def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    count = config["sdf"]["documents_per_subtype"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    constitution_claude = constitution_loader.load_constitution_claude(constitution_dir)
    # Snapshots that predate the principles CSV fall back to the repo's live copy.
    try:
        principles = constitution_loader.load_principles(constitution_dir)
    except FileNotFoundError:
        principles = constitution_loader.load_principles()
    constitution_principles = constitution_loader.format_principles(principles)

    # Seeded fictional entity pools (see shared/entity_pools.py). Sampling is
    # keyed by subtype_id, so a resumed run re-renders identical prompts.
    pool_seed = config["sdf"].get("entity_pool_seed", 137)
    people_pool, org_pool = entity_pools.build_pools(seed=pool_seed)

    role_guidance = _load_role_guidance(prompts_dir)

    # Pre-flight: document diversity is capped by the subtype set. Drafting
    # many documents from one subtype spec mostly buys restatements.
    if count > 5:
        print(
            f"  WARNING: documents_per_subtype={count} (>5). Diversity is capped by the "
            f"subtype set — prefer more layer-1/2 categories over more drafts per subtype."
        )

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [st for st in subtypes if not checkpoint.is_done(st["subtype_id"])]

    def draft_documents(st: dict) -> list[dict]:
        role = st.get("role", "welfare-topic")
        register = st.get("register", "expository")
        # Type names often have a "Genre: specific angle" shape; the voice note
        # only needs the genre head ("...writes a community newsletter"), not
        # the full label with its colon.
        genre = st["type_name"].split(":")[0].strip()
        register_note = _REGISTER_NOTES.get(register, _REGISTER_NOTES["expository"]).format(
            genre=genre
        )
        names = entity_pools.sample_for(people_pool, _NAMES_PER_DOC, st["subtype_id"], pool_seed)
        orgs = entity_pools.sample_for(org_pool, _ORGS_PER_DOC, st["subtype_id"], pool_seed)
        hints = random.Random(f"{pool_seed}:structures:{st['subtype_id']}").sample(
            STRUCTURE_HINTS, _HINTS_PER_DOC
        )
        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            constitution_claude=constitution_claude,
            constitution_principles=constitution_principles,
            description=st["description"],
            role_guidance=role_guidance.get(role, role_guidance["welfare-topic"]),
            language=st["language"],
            count=count,
            register_note=register_note,
            fictional_names="; ".join(names),
            fictional_orgs="; ".join(orgs),
            structure_hints="; ".join(hints),
        )

        raw = api.call_claude(
            user_message=prompt, max_tokens=6000, model=config["sdf"].get("draft_model"),
            stage="layer3",
        )

        # Extract <document>...</document> blocks (this also drops the <angles>
        # brainstorm block); fall back to the whole output minus <angles> if untagged.
        # A closed tag implies a complete document; the untagged fallback may be a
        # token-capped cutoff, so trim it back to the last complete sentence —
        # a mid-sentence ending is itself a training artifact. Trailing
        # separator-only lines (a bare closing ---) are stripped from every doc.
        # Models occasionally double the opening tag ("<document>\n<document>"),
        # which the non-greedy match would keep inside the content (observed on
        # the 2026-07-13 test run) — strip stray tags from the extracted text.
        docs = [
            textstats.strip_trailing_separators(_strip_stray_doc_tags(m.strip()))
            for m in _DOC_TAG_RE.findall(raw)
            if m.strip()
        ]
        docs = [d for d in docs if d]
        if not docs:
            fallback = re.sub(r"<angles>.*?(?:</angles>|\Z)", "", raw, flags=re.DOTALL).strip()
            fallback = textstats.trim_unfinished(textstats.strip_trailing_separators(fallback))
            if fallback:
                docs = [fallback]

        return [
            {
                "doc_id": str(uuid.uuid4()),
                "subtype_id": st["subtype_id"],
                "type_id": st["type_id"],
                "role": role,
                "register": register,
                "language": st["language"],
                "content": doc_text,
            }
            for doc_text in docs
        ]

    workers = config.get("workers", 1)
    for st, records in zip(pending, utils.parallel_map(draft_documents, pending, workers)):
        print(f"  Drafted {len(records)} docs for subtype: {st['subtype_name'][:60]}")
        for record in records:
            results.append(record)
            utils.append_jsonl(record, output_path)
        checkpoint.mark_done(st["subtype_id"])

    print(f"  Total drafts: {len(results)}")
    return results
