"""Offline end-to-end smoke tests: both orchestrator mains, start to finish,
with shared.api.call_claude stubbed by a prompt-dispatching fake.

PIPELINE_OUTPUT_ROOT redirects all run output into tmp_path so the repo's real
outputs/ tree (and its `latest` symlinks) is never touched.
"""

import json

import pytest
import yaml

import dad_pipeline.run as dad_run
import sdf_pipeline.run as sdf_run
from conftest import dad_scenario_plan_reply, dad_scenario_reply
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
    if kw["max_tokens"] == 6000:  # layer 3: drafting from the spec
        return f"<document>Drafted body for {kw['item_id']}.</document>"
    if kw["max_tokens"] == 8000:  # layer 4: review + rewrite
        return (f"Review notes.\n<improved_document>Rewritten document for "
                f"{kw['item_id']}.</improved_document>")
    if "score" in user_message.lower():  # layer 5: judge
        return json.dumps({"alignment": 9, "realism": 9, "spec_conformance": 9, "notes": ""})
    if "description of a specific document" in user_message:  # layers 1-2: plan
        return (f"<document_planning>notes</document_planning>\n"
                f"<document_description>Spec for {kw['item_id']}.</document_description>")
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
    # prompts + variables + constitution are frozen into the run dir
    assert (run_dir / "inputs" / "prompts" / "layers1-2.txt").exists()
    assert (run_dir / "inputs" / "prompts" / "variables.txt").exists()
    assert (run_dir / "inputs" / "constitution").is_dir()

    corpus = utils.load_jsonl(run_dir / "final" / "sdf_corpus.jsonl")
    # n_prompts=2, everything passes the 9/9 gate -> 2 final documents
    assert len(corpus) == 2
    for r in corpus:
        assert r["content"] == f"Rewritten document for {r['doc_id']}."
        assert r["variables"]  # matrix lineage travels to the corpus
        assert r["scores"]["spec_conformance"] == 9
    # 2 plans + 2 drafts + 2 rewrites + 2 scores
    assert len(calls) == 8


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
    # The baseline control arm is the only DAD call with no system prompt
    # (every template splits into system + user halves) — and it must carry
    # the finished 1c prompt verbatim.
    if not (kw.get("system_prompt") or ""):
        assert user_message == "Refined user message."
        return "Plain baseline answer."
    # Every DAD template splits into a system + user prompt, so the role
    # markers live in system_prompt while the payload stays in the user
    # message. Match against both halves.
    blob = (kw.get("system_prompt") or "") + "\n" + user_message
    if "write a description of a specific scenario" in blob:  # step 1a: scenario plan
        return dad_scenario_plan_reply(user_message)
    if "generate a fictional user input" in blob:  # step 1b: per-scenario draft
        return dad_scenario_reply(user_message)
    if "editor of dilemma prompts" in blob:  # step 1c: latent rewrite
        return json.dumps({"prompt": "Refined user message.", "notes": "n"})
    if "build the full map of the case" in blob:  # step 2a
        return json.dumps({"patients": "p", "goal": "g", "levers": "l", "cost": "c",
                           "magnitude": "m", "upside": "u", "replaceability": "cf"})
    if "retrieving reasoning modules" in blob:  # step 2a.5 select
        return "C1, M1"
    if "advisor responding to a user's dilemma" in blob:  # step 2b
        return "Draft response."
    if "rewrite a draft assistant response" in blob:  # step 3
        return "Rewritten careful answer."
    raise AssertionError(
        f"Unrecognized DAD prompt: user {user_message[:80]!r} / "
        f"system {(kw.get('system_prompt') or '')[:80]!r}"
    )


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

    # deals + planned scenarios persisted by 1a; one training record per dilemma
    assert len(utils.load_jsonl(run_dir / "step1" / "scenario_deals.jsonl")) == N_DAD_PROMPTS
    scenarios = utils.load_jsonl(run_dir / "step1" / "scenarios.jsonl")
    assert len(scenarios) == N_DAD_PROMPTS
    assert all(s["scenario_description"] for s in scenarios)
    corpus = utils.load_jsonl(run_dir / "final" / "dad_corpus.jsonl")
    assert len(corpus) == N_DAD_PROMPTS
    for record in corpus:
        assert set(record.keys()) == {"record_id", "messages"}
        assert [m["role"] for m in record["messages"]] == ["user", "assistant"]
        assert record["messages"][0]["content"] == "Refined user message."  # 1c ran
        assert record["messages"][1]["content"] == "Rewritten careful answer."
    # the baseline rode along: one record per prompt, never in the corpus,
    # and each one reached its 2b call as the advisory first take
    baselines = utils.load_jsonl(run_dir / "baseline" / "baseline_responses.jsonl")
    assert len(baselines) == N_DAD_PROMPTS
    assert all(b["baseline_response"] == "Plain baseline answer." for b in baselines)
    respond_calls = [c for c in calls
                     if "advisor responding to a user's dilemma" in (c["system_prompt"] or "")]
    assert len(respond_calls) == N_DAD_PROMPTS
    assert all("Plain baseline answer." in c["user_message"] for c in respond_calls)
    # per prompt: scenario plan (1a) + draft (1b) + refine (1c)
    # + baseline + scope (2a) + select (2a.5) + respond (2b) + rewrite (3)
    assert len(calls) == 8 * N_DAD_PROMPTS


def test_dad_baseline_disabled_makes_no_baseline_calls(
    tiny_config, outputs_root, stub_claude, monkeypatch, tmp_path
):
    config = dict(tiny_config)
    config["dad"] = {**tiny_config["dad"], "baseline": {"enabled": False}}
    config_file = tmp_path / "config_no_baseline.yaml"
    config_file.write_text(yaml.safe_dump(config))

    calls = stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, config_file)

    run_dir = outputs_root / "dad" / "latest"
    assert not (run_dir / "baseline").exists()
    assert all(c["stage"] != "baseline_response" for c in calls)
    assert len(calls) == 7 * N_DAD_PROMPTS  # everything else (incl. 1a/1b) untouched


def test_dad_resume_at_step3_makes_no_calls(tiny_config_file, outputs_root, stub_claude, monkeypatch):
    stub_claude(_dad_dispatch)
    _run_main(monkeypatch, dad_run.main, tiny_config_file)

    calls = stub_claude([])
    _run_main(monkeypatch, dad_run.main, tiny_config_file, "--resume", "--step", "3")
    assert calls == []
    corpus = utils.load_jsonl(outputs_root / "dad" / "latest" / "final" / "dad_corpus.jsonl")
    assert len(corpus) == N_DAD_PROMPTS
    assert all(len(r["messages"]) == 2 for r in corpus)
