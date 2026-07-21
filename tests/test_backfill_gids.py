"""Backfill of stable response/plain/example gids onto historical runs:
chronological numbering, content reuse, the final-corpus join, idempotence,
and the pre-registry-era guard."""

import json

from dad_pipeline.backfill_gids import backfill_run
from dad_pipeline.id_registry import IdRegistry
from shared import utils


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def _make_run(runs_root, name, *, gid_era=True, pairs=()):
    """A minimal run dir: dilemmas (gid-era or not) plus, per (pid, draft,
    rewritten, baseline) pair, matching step2/baseline/step3/final records."""
    run = runs_root / name
    _write_jsonl(run / "step1" / "dilemmas.jsonl",
                 [{"prompt_id": pid, "user_message": f"User q {pid}",
                   **({"prompt_gid": "P-0001", "scenario_gid": "S-0001"} if gid_era else {})}
                  for pid, *_ in pairs] or
                 [{"prompt_id": "AW-0001", "user_message": "u",
                   **({"prompt_gid": "P-0001"} if gid_era else {})}])
    responses, baselines, rewrites, finals = [], [], [], []
    for i, (pid, draft, rewritten, baseline_text) in enumerate(pairs):
        record_id = f"rec-{name}-{i}"
        responses.append({"response_id": f"uuid-{name}-{i}", "prompt_id": pid,
                          "sample_index": 0, "user_message": f"User q {pid}",
                          "assistant_response": draft})
        if baseline_text:
            baselines.append({"prompt_id": pid, "user_message": f"User q {pid}",
                              "baseline_response": baseline_text, "model": "m"})
        rewrites.append({"record_id": record_id, "response_id": f"uuid-{name}-{i}",
                         "prompt_id": pid, "sample_index": 0,
                         "user_message": f"User q {pid}",
                         "draft_response": draft, "rewritten_response": rewritten})
        finals.append({"record_id": record_id,
                       "messages": [{"role": "user", "content": f"User q {pid}"},
                                    {"role": "assistant", "content": rewritten}]})
    if responses:
        _write_jsonl(run / "step2" / "responses.jsonl", responses)
    if baselines:
        _write_jsonl(run / "baseline" / "baseline_responses.jsonl", baselines)
    if rewrites:
        _write_jsonl(run / "step3" / "rewrites.jsonl", rewrites)
    if finals:
        _write_jsonl(run / "final" / "dad_corpus.jsonl", finals)
    return run


def test_labels_all_files_and_joins_the_final_corpus(tmp_path):
    runs_root = tmp_path / "runs"
    run = _make_run(runs_root, "2026-07-12_00-00_a",
                    pairs=[("AW-0001", "draft one", "rewritten one", "plain one")])
    registry = IdRegistry(tmp_path / "id_registry.json")

    counts = backfill_run(run, registry)

    assert counts == {"step2/responses.jsonl": 1,
                      "baseline/baseline_responses.jsonl": 1,
                      "step3/rewrites.jsonl": 1,
                      "final/dad_corpus.jsonl": 1}
    resp = utils.load_jsonl(run / "step2" / "responses.jsonl")[0]
    assert resp["response_gid"] == "R-0001"
    # the gid sits next to its per-run sibling id, like pipeline-written records
    assert list(resp)[:2] == ["response_id", "response_gid"]
    assert utils.load_jsonl(run / "baseline" / "baseline_responses.jsonl")[0]["plain_gid"] == "C-0001"
    rw = utils.load_jsonl(run / "step3" / "rewrites.jsonl")[0]
    # the rewrite carries the step-2 draft verbatim, so content-keying lands
    # on the same R- number with no join
    assert rw["response_gid"] == "R-0001"
    assert rw["example_gid"] == "E-0001"
    final = utils.load_jsonl(run / "final" / "dad_corpus.jsonl")[0]
    assert final["example_gid"] == "E-0001"
    assert final["response_gid"] == "R-0001"  # joined through record_id


def test_numbers_continue_chronologically_and_content_is_reused(tmp_path):
    runs_root = tmp_path / "runs"
    run_a = _make_run(runs_root, "2026-07-12_00-00_a",
                      pairs=[("AW-0001", "draft one", "rewritten one", "plain one")])
    run_b = _make_run(runs_root, "2026-07-13_00-00_b",
                      pairs=[("AW-0001", "draft one", "rewritten two", "plain two")])
    registry = IdRegistry(tmp_path / "id_registry.json")
    for run in sorted(runs_root.iterdir()):
        backfill_run(run, registry)

    # run B reused run A's draft text -> same R-; its rewrite differs -> new E-
    assert utils.load_jsonl(run_a / "step2" / "responses.jsonl")[0]["response_gid"] == "R-0001"
    assert utils.load_jsonl(run_b / "step2" / "responses.jsonl")[0]["response_gid"] == "R-0001"
    assert utils.load_jsonl(run_a / "step3" / "rewrites.jsonl")[0]["example_gid"] == "E-0001"
    assert utils.load_jsonl(run_b / "step3" / "rewrites.jsonl")[0]["example_gid"] == "E-0002"
    assert utils.load_jsonl(run_b / "baseline" / "baseline_responses.jsonl")[0]["plain_gid"] == "C-0002"


def test_pre_registry_runs_are_left_untouched(tmp_path):
    runs_root = tmp_path / "runs"
    run = _make_run(runs_root, "2026-07-06_00-00_old", gid_era=False,
                    pairs=[("AW-0001", "draft", "rewritten", "plain")])
    before = (run / "step2" / "responses.jsonl").read_text()

    counts = backfill_run(run, IdRegistry(tmp_path / "id_registry.json"))

    assert counts == {}
    assert (run / "step2" / "responses.jsonl").read_text() == before


def test_second_pass_is_a_no_op(tmp_path):
    runs_root = tmp_path / "runs"
    run = _make_run(runs_root, "2026-07-12_00-00_a",
                    pairs=[("AW-0001", "draft", "rewritten", "plain")])
    registry = IdRegistry(tmp_path / "id_registry.json")
    backfill_run(run, registry)
    snapshot = {p.name: p.read_text() for p in run.rglob("*.jsonl")}

    assert backfill_run(run, registry) == {}
    assert {p.name: p.read_text() for p in run.rglob("*.jsonl")} == snapshot


def test_dry_run_reports_without_writing(tmp_path):
    runs_root = tmp_path / "runs"
    run = _make_run(runs_root, "2026-07-12_00-00_a",
                    pairs=[("AW-0001", "draft", "rewritten", "plain")])
    before = (run / "step2" / "responses.jsonl").read_text()

    counts = backfill_run(run, IdRegistry(tmp_path / "id_registry.json"), dry_run=True)

    assert counts["step2/responses.jsonl"] == 1
    assert (run / "step2" / "responses.jsonl").read_text() == before
