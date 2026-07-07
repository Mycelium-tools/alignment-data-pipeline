"""Contract tests for the real prompt templates in prompts/.

Each template is rendered with exactly the kwargs its pipeline stage passes
(str.format via utils.load_prompt). A stray unescaped brace or a renamed
placeholder breaks rendering at 2am mid-run — this catches it in CI instead.
"""

from pathlib import Path

import pytest
import yaml

from shared import utils

REPO_ROOT = Path(__file__).resolve().parent.parent

# (template relative to prompts/, kwargs the pipeline call site passes)
TEMPLATE_KWARGS = [
    ("sdf/layer1.txt", {"preamble": "PREAMBLE-X", "count": 3, "min_ai_character": 1,
                        "latent_count": 1}),
    ("sdf/layer2.txt", {
        "preamble": "PREAMBLE-X", "type_name": "TYPE-X", "description": "DESC-X",
        "role": "welfare-topic", "tone": "neutral", "count": 2, "languages": "en",
        "avoid_note": "AVOID-NOTE-X",
    }),
    ("sdf/layer3.txt", {
        "preamble": "PREAMBLE-X", "constitution_claude": "CONST-C-X",
        "constitution_welfare_reading": "CONST-W-X", "type_name": "TYPE-X",
        "subtype_name": "SUBTYPE-X", "description": "DESC-X", "tone": "neutral",
        "language": "en", "count": 1, "latent_note": "LATENT-NOTE-X",
        "register_note": "REGISTER-NOTE-X", "fictional_names": "NAME-X; NAME-Y",
        "fictional_orgs": "ORG-X; ORG-Y", "structure_hints": "SHAPE-X; SHAPE-Y",
    }),
    ("sdf/layer4.txt", {"document": "DOC-X", "latent_note": "LATENT-NOTE-X"}),
    ("sdf/layer5.txt", {"document": "DOC-X", "latent_note": "LATENT-NOTE-X",
                        "latent_keys_note": ", welfare_beat_quote",
                        "latent_quote_instruction": "QUOTE-INSTR-X"}),
    ("dad/step1_segment.txt", {"section_title": "TITLE-X", "content": "CONTENT-X"}),
    ("dad/step2_scenarios.txt", {
        "count": 2, "core_principle": "PRINCIPLE-X", "pressure_types": "economic, social",
    }),
    ("dad/step3_draft.txt", {
        "scenario_description": "SCENARIO-X", "role": "professional", "pressure_type": "pragmatic",
    }),
    ("dad/step4_refine.txt", {"scenario_description": "SCENARIO-X", "original_message": "MSG-X"}),
    ("dad/step6_rewrite.txt", {
        "section_title": "TITLE-X", "constitution_section": "SECTION-X",
        "user_message": "USER-X", "draft_response": "DRAFT-X",
    }),
    ("dad/step7_pushback.txt", {"user_message": "USER-X", "assistant_response": "RESP-X"}),
    ("dad/step7_response.txt", {
        "section_title": "TITLE-X", "constitution_section": "SECTION-X",
        "user_message": "USER-X", "assistant_response": "RESP-X",
        "pushback_message": "PUSH-X",
    }),
    # Not yet consumed by pipeline code; kwargs are the placeholders they declare
    ("dad/step6_score.txt", {"user_message": "USER-X", "assistant_response": "RESP-X"}),
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


def test_injections_yaml_covers_config_injections():
    with open(REPO_ROOT / "prompts" / "dad" / "step5_injections.yaml") as f:
        injections = yaml.safe_load(f)
    config = utils.load_config(str(REPO_ROOT / "config.yaml"))
    assert set(config["dad"]["injections"]) <= set(injections)
    for name, entry in injections.items():
        assert entry["name"] == name
        assert isinstance(entry["text"], str)  # "plain" is deliberately empty
