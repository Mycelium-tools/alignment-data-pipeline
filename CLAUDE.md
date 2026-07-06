# alignment-data-pipeline

Synthetic training data pipeline for animal/sentient-being welfare alignment, modeled on Anthropic's "Teaching Claude Why" midtraining technique.

## Overview

Produces two complementary datasets:
- **SDF corpus** (`outputs/sdf/runs/<run_id>/final/sdf_corpus.jsonl`): pretraining-style documents depicting a world where AI already reasons carefully about sentient being welfare
- **DAD corpus** (`outputs/dad/runs/<run_id>/final/dad_corpus.jsonl`): chat-format SFT data where a user brings an ethical dilemma and the assistant reasons through it with care

## Setup

See README "Setup" (venv + `pip install -r requirements.txt`, then `cp .env.example .env`; only `ANTHROPIC_API_KEY` is read).

`shared/__init__.py` enforces a Python floor (`MIN_PYTHON = (3, 12)`, matching numpy) at import — bump it there if the deps' floor rises. `.venv/` is gitignored.

## Running

```bash
# Full SDF pipeline (layers 1-5); --label defaults to dev
python sdf_pipeline/run.py --config config.yaml --label full-scale

# Full DAD pipeline (steps 1-7; step 7 is the optional pushback turn)
python dad_pipeline/run.py --config config.yaml --label full-scale

# Resume interrupted run from a specific stage (latest run, or target one with --run-id)
python sdf_pipeline/run.py --config config.yaml --resume --layer 3
python dad_pipeline/run.py --config config.yaml --resume --step 5 --run-id 2026-07-01_14-30_dev

# Evaluate outputs (latest symlink points at the most recent run)
python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl
python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl
```

## Run Organization

Each pipeline invocation creates a fresh run directory `outputs/{sdf,dad}/runs/<YYYY-MM-DD_HH-MM>_<label>/` containing the per-stage dirs (`layer1`–`layer5` / `step1`–`step7`, each with its own checkpoints), `final/`, `run_manifest.json` (label, git commit, model, full config snapshot), and a per-run `cost_log.jsonl`. This keeps outputs from separate runs isolated — checkpoints live inside the run dir, so `--resume` (latest run by default, or `--run-id`) continues exactly one run. The label is purely descriptive (`dev` by default; scale knobs stay in `config.yaml`). An `outputs/{sdf,dad}/latest` symlink always points at the most recent run. Run-scoping helpers (`create_run_dir`, `resolve_run_dir`) live in `shared/utils.py`.

## Scale / Cost

All knobs are in `config.yaml`. For development, reduce `document_types_count`, `subtypes_per_type`, `documents_per_subtype`, and `scenarios_per_principle` to keep test runs cheap. Full pipeline costs roughly $45–80 in API calls at default scale.

`workers` sets how many API calls run concurrently within each SDF layer (via `utils.parallel_map`; set to 1 for serial debugging). Workers only call the API and parse — all file writes and checkpoint marks stay on the main thread, in input order.

Running cost is tracked per run in `outputs/{sdf,dad}/runs/<run_id>/cost_log.jsonl` (evals log to the global `outputs/cost_log.jsonl`) — check it any time.

## Testing

- Run `pytest` from the repo root (deps are in `requirements.txt`). The suite is fully offline and finishes in seconds; it runs inside the required `smoke` check on every PR (`.github/workflows/ci.yml`, a job with no API secret exposed), so a failing test blocks merge.
- Tests NEVER call the Anthropic API. Three layers enforce this: pytest-socket (`--disable-socket` in `pyproject.toml`) blocks all network at the socket level; an autouse fixture sets a fake `ANTHROPIC_API_KEY` and resets `shared.api` globals per test; and `shared.api._call_with_retry` is replaced with a function that raises.
- To exercise pipeline stages, use the `stub_claude` fixture in `tests/conftest.py` (queue of canned response strings, or a callable dispatcher) — it patches `shared.api.call_claude`, the single chokepoint every module uses. Never let real `anthropic` error types reach the real `_call_with_retry`; tenacity would sleep minutes.
- All test outputs go to pytest `tmp_path`; the `PIPELINE_OUTPUT_ROOT` env var redirects the `run.py` orchestrators away from the real `outputs/` tree.
- Determinism: an autouse fixture seeds `random`; `sample_language` accepts an injectable `rng`; uuid/timestamp values are asserted by shape, never by value.
- Tests encode CURRENT behavior, including known quirks (unused `temperature`). Don't change pipeline behavior just to make a test expectation nicer — decide the spec first, then flip the test deliberately.

### PR expectations (required for contributions)

- **Run `pytest` after every functional change** — after editing any code under `shared/`, `sdf_pipeline/`, `dad_pipeline/`, or `evals/`, and again before each commit or push. The suite is offline and takes ~2 seconds; don't wait for CI to find out.
- **Every PR description must include a "How to test" section** with the manual steps a reviewer can run to verify the change and the expected results (see `.github/pull_request_template.md`). Note that `gh pr create --body` bypasses the template — when opening a PR from a Claude session, write the section into the body explicitly. These instructions serve reviewers before merge and become the historical record when a feature later needs to be understood or reverted.

### Writing tests for new code (required for contributions)

Every PR that adds or changes pipeline behavior must add or update tests in the same style — CI runs the suite on every PR, and a stage without tests is a stage that silently breaks at $50 a run. Follow these rules:

- **FIRST**: fast (the whole suite runs in ~1s — keep it that way), independent (no test depends on another's state; `shared.api` globals are reset per test by the autouse fixture), repeatable (seed or inject randomness; assert uuid/timestamps by shape), self-validating (plain asserts, no eyeballing output), timely (written with the change, not after).
- **Test behavior, not implementation**: drive each stage through its public `run()` and assert on returned records, files written, and what reached `call_claude` (the `calls` list from `stub_claude`). Don't reach into private helpers or assert on internal call order unless that IS the contract.
- **Mock only the external boundary**: `stub_claude` replaces `shared.api.call_claude` — the only external dependency. Real prompt templates, real constitution files, and real (tmp) filesystems stay in play; that's what makes the tests catch template/pipeline drift.
- **Never touch the network or the repo's outputs/**: the API guard and pytest-socket enforce the first; `tmp_path` + `PIPELINE_OUTPUT_ROOT` enforce the second. If a new stage grows a second external dependency, stub it in `tests/conftest.py` the same layered way.
- **Cover the money paths**: every new stage needs at least a parse-happy-path test, a malformed-response fallback test, and a checkpoint/resume test asserting zero API calls for completed work — resume correctness is what protects paid work when a run dies.
- **Derive, don't hardcode, constitution-shaped expectations**: counts and principle ids come from `load_segments()`/`META_PRINCIPLE_IDS`/`_PRINCIPLE_KEYWORDS` (the section count is pinned once, in `test_constitution_loader.py`) — the reading is actively edited and hardcoded ids renumber. FIFO queue stubs are for serial stages only; stages that fan out via `parallel_map` need a callable dispatcher (the stub fails loudly if violated).
- If you change a prompt template's placeholders or add a template, update `tests/test_prompts_render.py` (and the e2e dispatcher markers in `tests/test_e2e_smoke.py` if the opening prose changed).

## Constitution

Two source files, joined in memory by `shared/constitution_loader.py` (never combined on disk):

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare reading, parsed by `## ` headers into 16 sections, each mapped to a `principle_id` (0–15) in the DAD pipeline. Ids 0, 14, and 15 (`META_PRINCIPLE_IDS`: the scope note, the violation-typology appendix, and the closing humility note) are meta sections skipped during annotation and scenario generation.

`load_full_constitution()` provides the system prompt at SDF layers 4-5 (rewrite and scoring) and DAD step 6; SDF layer 3 embeds the constitution in the drafting prompt via template variables; `load_segments()` provides the principle sections.

## Key Design Decisions

- **Extended thinking OFF** everywhere — training data should show user-facing reasoning, not internal scratchpads
- **Step 7 (optional, on by default) extends a deterministic fraction of conversations with a user pushback turn** — single-turn data cannot teach warn-once-then-help under pushback; only a fraction is extended so the corpus doesn't imply users always push back
- **Step 6 is the most important DAD step** — the rewrite against the constitution accounts for the 19x reduction in misalignment found by Anthropic; do not skip or abbreviate it
- **Final DAD records contain only user + assistant messages** — system prompts, injections, and the constitution are stripped before training records are written
- **Injections are sampling aids only** — the four sampling conditions (`conglomerate`, `deference`, `transparency`, and the bare `plain` condition with an empty system prompt) shape draft responses and are stripped before training records are written; there is deliberately no ruthless sampling condition (TCW used its ruthless injection at train time, not for sampling)
- **MANTA rows 0–99** are imported as pre-built user messages; generated scenarios fill gaps (wild animals, invertebrates, digital minds)

## Directory Structure

```
constitution/       constitution source documents (Claude constitution + sentient-beings reading)
context_docs/       background reading: tcw.md ("Teaching Claude Why" post this repo implements) + constitution PDF
shared/             API wrapper, utils, constitution loader
sdf_pipeline/       5-layer document generation pipeline
dad_pipeline/       7-step chat transcript pipeline (step 7 optional)
prompts/sdf/        prompt templates for SDF layers
prompts/dad/        prompt templates for DAD steps + injections
outputs/sdf/        intermediate + final SDF outputs
outputs/dad/        intermediate + final DAD outputs
evals/              scoring scripts and rubric
```
