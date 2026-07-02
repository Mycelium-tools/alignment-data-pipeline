"""Load and segment the constitution documents.

Two source files live in constitution/:
- constitution_claude.md — the original Claude constitution, verbatim.
- constitution_sentient_beings.md — the animal-welfare section-by-section
  reading, with one `## ` header per section.

They are joined in memory wherever the full text is needed — the system
prompts of SDF layers 4-5 (rewrite and scoring) and DAD step 6; SDF layer 3
embeds the two texts via template variables instead. Only the sentient-beings
reading is segmented into principles for the DAD pipeline.
"""

from pathlib import Path

_CONSTITUTION_DIR = Path(__file__).parent.parent / "constitution"
_CLAUDE_PATH = _CONSTITUTION_DIR / "constitution_claude.md"
_SENTIENT_PATH = _CONSTITUTION_DIR / "constitution_sentient_beings.md"

_JOIN_PREAMBLE = """\
This document joins two complementary frameworks:
Part I: The original claude constitution
Part II: A reading of the original constitution

The Part II document does not modify, extend, or rewrite Claude's Constitution. It
reads it. For each section of the constitution that bears on the treatment
of animals and other sentient beings, it quotes the section verbatim and then
explains what that section already implies, given that the constitution
already directs Claude to weigh "the welfare of animals and of all sentient
beings." Our own contributions appear only as interpretation, as labeled
heuristics, as examples, and as citations to authoritative outside documents —
never as words put into the constitution's mouth.
"""

# Sections of the reading that describe the document itself rather than a
# principle usable for scenario generation (scope note, closing humility note).
META_PRINCIPLE_IDS = {0, 11}


def load_constitution_claude() -> str:
    """Return the original Claude constitution, verbatim."""
    return _CLAUDE_PATH.read_text()


def load_constitution_welfare_reading() -> str:
    """Return the sentient-beings reading of the constitution, verbatim."""
    return _SENTIENT_PATH.read_text()


def load_full_constitution() -> str:
    """Return the full constitution: join preamble + Claude constitution + reading. Used as the system prompt at SDF layers 4-5 and DAD step 6; SDF layer 3 embeds the constitution via template variables instead."""
    return "\n---\n\n".join([
        _JOIN_PREAMBLE,
        _CLAUDE_PATH.read_text(),
        _SENTIENT_PATH.read_text(),
    ])


def load_segments() -> list[dict]:
    """Split the sentient-beings reading on '## ' headers.

    Returns:
        List of {"section_title", "content", "principle_id"} dicts, one per
        section, with principle_id assigned in file order (0-11).
    """
    segments, current_title, current_lines = [], None, []
    for line in _SENTIENT_PATH.read_text().splitlines():
        if line.startswith("## "):
            if current_title and current_lines:
                segments.append({"section_title": current_title, "content": "\n".join(current_lines).strip()})
            current_title, current_lines = line[3:].strip(), []
        elif current_title is not None:
            current_lines.append(line)
    if current_title and current_lines:
        segments.append({"section_title": current_title, "content": "\n".join(current_lines).strip()})
    for i, seg in enumerate(segments):
        seg["principle_id"] = i
    return segments
