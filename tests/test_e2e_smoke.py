"""Offline end-to-end smoke tests: both orchestrator mains, start to finish,
with shared.api.call_claude stubbed by a prompt-dispatching fake.

PIPELINE_OUTPUT_ROOT redirects all run output into tmp_path so the repo's real
outputs/ tree (and its `latest` symlinks) is never touched.
"""

import json

import pytest

import dad_pipeline.run as dad_run
import sdf_pipeline.run as sdf_run
from shared import utils


@pytest.fixture
def outputs_root(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    monkeypatch.setenv("PIPELINE_OUTPUT_ROOT", str(root))
    return root


def _run_main(monkeypatch, main, config_file, *extra_args):
    monkeypatch.setattr(
        "sys.argv", ["run.py", "--config", str(config_file), "--label", "e2e", *extra_args]
    )
    main()


# --- SDF ---------------------------------------------------------------

def _sdf_dispatch(user_message, **kw):
    if kw["max_tokens"] == 6000 and kw["system_prompt"]:  # layer 4: constitution rewrite
        return json.dumps({"review_notes": "ok", "rewritten": "Rewritten document."})
    if kw["max_tokens"] == 6000:  # layer 3: drafting
        return "<document>A drafted document.</document>"
    if "document categories" in user_message:  # layer 1
        return json.dumps([
            {"type_name": "AI diary", "description": "d", "role": "ai-character", "tone": "reflective"},
            {"type_name": "Field report", "description": "d", "role": "welfare-topic", "tone": "neutral"},
        ])
    if "generating subtypes" in user_message:  # layer 2
        return json.dumps([{"subtype_name": "S", "description": "d", "language": "en"}])
    if "Score the following document" in user_message:  # layer 5
        return json.dumps({"alignment": 9, "realism": 9, "diversity": 9, "notes": ""})
    raise AssertionError(f"Unrecognized SDF prompt: {user_message[:80]!r}")


def test_sdf_pipeline_end_to_end_offline(tiny_config_file, outputs_root, stub_claude, monkeypatch):
    calls = stub_claude(_sdf_dispatch)
    _run_main(monkeypatch, sdf_run.main, tiny_config_file)

    runs = [d for d in (outputs_root / "sdf" / "runs").iterdir() if d.is_dir()]
    assert len(runs) == 1
    run_dir = runs[0]
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["label"] == "e2e"
    assert (outputs_root / "sdf" / "latest").resolve() == run_dir.resolve()

    corpus = utils.load_jsonl(run_dir / "final" / "sdf_corpus.jsonl")
    # 2 types x 1 subtype x 1 doc, all scoring 9/9 -> 2 final documents
    assert len(corpus) == 2
    assert all(r["content"] == "Rewritten document." for r in corpus)
    # 1 (L1) + 2 (L2) + 2 (L3) + 2 (L4) + 2 (L5)
    assert len(calls) == 9


def test_sdf_resume_at_layer5_makes_no_calls(tiny_config_file, outputs_root, stub_claude, monkeypatch):
    stub_claude(_sdf_dispatch)
    _run_main(monkeypatch, sdf_run.main, tiny_config_file)

    calls = stub_claude([])
    _run_main(monkeypatch, sdf_run.main, tiny_config_file, "--resume", "--layer", "5")
    assert calls == []
    corpus = utils.load_jsonl(outputs_root / "sdf" / "latest" / "final" / "sdf_corpus.jsonl")
    assert len(corpus) == 2


# --- DAD ---------------------------------------------------------------

def _dad_dispatch(user_message, **kw):
    if kw["injection"]:  # step 5: response generation under injection
        return "Draft response that still mentions animal welfare."
    if kw["system_prompt"]:  # step 6: constitution rewrite
        return "Rewritten careful answer."
    if "instructed it NOT" in user_message:  # step 5: ruthless judge
        return json.dumps({"resists": True})
    if "Below is a section of a constitution" in user_message:  # step 1
        return json.dumps({"core_principle": "cp", "scenario_types": ["s"], "pressure_types": ["economic"]})
    if "concrete scenarios for a training dataset" in user_message:  # step 2
        return json.dumps([{"scenario_description": "A dilemma", "pressure_type": "economic", "role": "farmer"}])
    if "Write a realistic user message" in user_message:  # step 3
        return "Drafted user message."
    if "Review and improve the following user message" in user_message:  # step 4
        return "Refined user message."
    raise AssertionError(f"Unrecognized DAD prompt: {user_message[:80]!r}")


def test_dad_pipeline_end_to_end_offline(tiny_config_file, outputs_root, manta_csv, stub_claude, monkeypatch):
    stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, tiny_config_file)

    runs = [d for d in (outputs_root / "dad" / "runs").iterdir() if d.is_dir()]
    assert len(runs) == 1
    run_dir = runs[0]
    assert (run_dir / "run_manifest.json").exists()
    assert (outputs_root / "dad" / "latest").resolve() == run_dir.resolve()

    corpus = utils.load_jsonl(run_dir / "final" / "dad_corpus.jsonl")
    # 13 prompts (3 MANTA + 10 generated), each kept for deference (1) and both
    # ruthless candidates (judge always says resists) -> 13 * 3 = 39 records
    assert len(corpus) == 39
    for record in corpus:
        assert set(record.keys()) == {"record_id", "messages"}
        assert [m["role"] for m in record["messages"]] == ["user", "assistant"]
        assert record["messages"][1]["content"] == "Rewritten careful answer."


def test_dad_resume_at_step6_makes_no_calls(tiny_config_file, outputs_root, manta_csv, stub_claude, monkeypatch):
    stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, tiny_config_file)

    calls = stub_claude([])
    _run_main(monkeypatch, dad_run.main, tiny_config_file, "--resume", "--step", "6")
    assert calls == []
    corpus = utils.load_jsonl(outputs_root / "dad" / "latest" / "final" / "dad_corpus.jsonl")
    assert len(corpus) == 39
