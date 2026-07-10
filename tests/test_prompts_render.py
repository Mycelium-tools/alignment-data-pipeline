"""Contract tests for the real prompt templates in prompts/.

Each template is rendered with exactly the kwargs its pipeline stage passes
(str.format via utils.load_prompt). A stray unescaped brace or a renamed
placeholder breaks rendering at 2am mid-run — this catches it in CI instead.
"""

from pathlib import Path

import pytest

from shared import utils

REPO_ROOT = Path(__file__).resolve().parent.parent

# (template relative to prompts/, kwargs the pipeline call site passes)
TEMPLATE_KWARGS = [
    ("sdf/layer1.txt", {"preamble": "PREAMBLE-X", "count": 3, "min_ai_character": 1}),
    ("sdf/layer2.txt", {
        "preamble": "PREAMBLE-X", "type_name": "TYPE-X", "description": "DESC-X",
        "tone": "neutral", "count": 2, "languages": "en", "avoid_note": "AVOID-NOTE-X",
    }),
    ("sdf/layer3.txt", {
        "preamble": "PREAMBLE-X", "subtype": "SUBTYPE-BLOCK-X", "CONSTITUTION": "CONST-X",
    }),
    # layer4.txt is TCW's one-file "System prompt: / User:" format; the code
    # splits it before rendering, but a full-file render covers both halves.
    ("sdf/layer4.txt", {"CONSTITUTION": "CONST-X", "document": "DOC-X"}),
    ("sdf/layer5.txt", {"document": "DOC-X"}),
    ("dad/step1_dilemmas.txt", {"count": 2, "scenarios_block": "SCENARIO-BLOCK-X"}),
    ("dad/step1_refine.txt", {"scenario_block": "SCENARIO-BLOCK-X", "draft_prompt": "DRAFT-X",
                              "annotation_block": "ANNOTATION-X"}),
    ("dad/step2_scope.txt", {"user_message": "USER-X"}),
    ("dad/step2_respond.txt", {
        "library_block": "LIBRARY-X", "scope_block": "SCOPE-X", "user_message": "USER-X",
    }),
    ("dad/step3_rewrite.txt", {
        "principles_block": "PRINCIPLES-X",
        "user_message": "USER-X", "draft_response": "DRAFT-X",
    }),
    # Not yet consumed by pipeline code; kwargs are the placeholders they declare
    ("dad/step3_score.txt", {
        "user_message": "USER-X", "assistant_response": "RESP-X",
        "intended_direction": "Under-weighting", "user_attitude": "Neutral / Curious",
    }),
    ("tools/pattern_scan.txt", {"documents": "DOCS-X"}),
]


@pytest.mark.parametrize("rel_path,kwargs", TEMPLATE_KWARGS, ids=[t[0] for t in TEMPLATE_KWARGS])
def test_template_renders_with_pipeline_kwargs(rel_path, kwargs):
    path = REPO_ROOT / "prompts" / rel_path
    raw = path.read_text()
    rendered = utils.load_prompt(path, **kwargs)
    assert rendered.strip()
    # Every placeholder the template declares must be filled with our value
    for name, value in kwargs.items():
        if "{" + name + "}" in raw:
            assert str(value) in rendered, f"{{{name}}} not substituted in {rel_path}"


def test_preamble_loads_verbatim():
    text = utils.load_prompt(REPO_ROOT / "prompts" / "sdf" / "preamble.txt")
    assert text.strip()


def test_reasoning_library_loads_with_expected_layers():
    """The library CSV is step 2's source of truth: every entry carries the
    schema columns, and all three layers (conduct C*, core moves M*, topic T*)
    are present. Counts are asserted loosely — the library is actively edited."""
    from dad_pipeline import reasoning_library

    library = reasoning_library.load(REPO_ROOT / "prompts" / "dad")
    ids = reasoning_library.all_ids(library)
    assert len(ids) == len(set(ids)), "duplicate entry ids in reasoning_library.csv"
    prefixes = {i[0] for i in ids}
    assert {"C", "M", "T"} <= prefixes
    block = reasoning_library.format_library(library)
    assert all(i in block for i in ids)
