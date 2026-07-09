"""Offline end-to-end smoke tests: both orchestrator mains, start to finish,
with shared.api.call_claude stubbed by a prompt-dispatching fake.

PIPELINE_OUTPUT_ROOT redirects all run output into tmp_path so the repo's real
outputs/ tree (and its `latest` symlinks) is never touched.
"""

import json

import pytest

import dad_pipeline.run as dad_run
import sdf_pipeline.run as sdf_run
from conftest import dad_scenario_reply
from shared import utils

N_DAD_PROMPTS = 2  # tiny_config dad.dilemmas.count


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
        return "Review notes.\n<improved_document>Rewritten document.</improved_document>"
    if kw["max_tokens"] == 6000:  # layer 3: drafting
        return "<angles>brainstorm</angles>\n<document>A drafted document.</document>"
    if kw["system_prompt"]:  # layer 5: scoring against the constitution
        return json.dumps({"alignment": 9, "realism": 9, "diversity": 9, "notes": ""})
    if "document categories" in user_message:  # layer 1
        return json.dumps([
            {"type_name": "AI diary", "description": "d", "role": "ai-character", "tone": "reflective"},
            {"type_name": "Field report", "description": "d", "role": "welfare-topic", "tone": "neutral"},
        ])
    if "expanding one document category" in user_message:  # layer 2
        return json.dumps([{"subtype_name": "S", "description": "d", "language": "en"}])
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
    # prompts + constitution are frozen into the run dir for reproducibility
    assert (run_dir / "inputs" / "prompts" / "layer1.txt").exists()
    assert (run_dir / "inputs" / "constitution").is_dir()

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
    if "first-attempt user prompts" in user_message:  # step 1b: batch draft
        return dad_scenario_reply(user_message)
    if "dilemma-prompt rewrite step" in user_message:  # step 1c: latent rewrite
        return json.dumps({"prompt": "Refined user message.", "notes": "n"})
    if "scoping an animal-welfare advice dilemma" in user_message:  # step 2a
        return json.dumps({"patients": "p", "levers": "l", "cost": "c",
                           "upside": "u", "counterfactual": "cf"})
    if "writing the assistant's response" in user_message:  # step 2b
        return "Draft response."
    if "rewriting a draft assistant response" in user_message:  # step 3
        return "Rewritten careful answer."
    raise AssertionError(f"Unrecognized DAD prompt: {user_message[:80]!r}")


def test_dad_pipeline_end_to_end_offline(tiny_config_file, outputs_root, stub_claude, monkeypatch):
    calls = stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, tiny_config_file)

    runs = [d for d in (outputs_root / "dad" / "runs").iterdir() if d.is_dir()]
    assert len(runs) == 1
    run_dir = runs[0]
    assert (run_dir / "run_manifest.json").exists()
    assert (outputs_root / "dad" / "latest").resolve() == run_dir.resolve()
    assert (run_dir / "inputs" / "prompts" / "step3_rewrite.txt").exists()
    assert (run_dir / "inputs" / "constitution").is_dir()

    # scenarios persisted by 1a; one training record per dilemma
    assert len(utils.load_jsonl(run_dir / "step1" / "scenarios.jsonl")) == N_DAD_PROMPTS
    corpus = utils.load_jsonl(run_dir / "final" / "dad_corpus.jsonl")
    assert len(corpus) == N_DAD_PROMPTS
    for record in corpus:
        assert set(record.keys()) == {"record_id", "messages"}
        assert [m["role"] for m in record["messages"]] == ["user", "assistant"]
        assert record["messages"][0]["content"] == "Refined user message."  # 1c ran
        assert record["messages"][1]["content"] == "Rewritten careful answer."
    # 1 batch draft, then per prompt: refine (1c) + scope (2a) + respond (2b) + rewrite (3)
    assert len(calls) == 1 + 4 * N_DAD_PROMPTS


def test_dad_resume_at_step3_makes_no_calls(tiny_config_file, outputs_root, stub_claude, monkeypatch):
    stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, tiny_config_file)

    calls = stub_claude([])
    _run_main(monkeypatch, dad_run.main, tiny_config_file, "--resume", "--step", "3")
    assert calls == []
    corpus = utils.load_jsonl(outputs_root / "dad" / "latest" / "final" / "dad_corpus.jsonl")
    assert len(corpus) == N_DAD_PROMPTS
    assert all(len(r["messages"]) == 2 for r in corpus)
