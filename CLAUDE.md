# alignment-data-pipeline

Synthetic training data pipeline for animal/sentient-being welfare alignment, modeled on Anthropic's "Teaching Claude Why" midtraining technique.

## Overview

Produces two complementary datasets:
- **SDF corpus** (`outputs/sdf/runs/<run_id>/final/sdf_corpus.jsonl`): pretraining-style documents depicting a world where AI already reasons carefully about sentient being welfare
- **DAD corpus** (`outputs/dad/runs/<run_id>/final/dad_corpus.jsonl`): chat-format SFT data where a user brings an ethical dilemma and the assistant reasons through it with care

## Setup

See README "Setup" (venv + `pip install -r requirements.txt`, then `cp .env.example .env`). Auth depends on the `backend` key in `config.yaml`: `api` (default) reads `ANTHROPIC_API_KEY`; `claude_code` bills the contributor's Claude subscription via the Claude Code CLI (logged-in session or `CLAUDE_CODE_OAUTH_TOKEN`) — use it for dev runs, keep `api` for full-scale runs. See README "Authentication" for caveats (usage windows, notional cost logging).

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

## Constitution

Two source files, joined in memory by `shared/constitution_loader.py` (never combined on disk):

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare reading, parsed by `## ` headers into 12 sections, each mapped to a `principle_id` (0–11) in the DAD pipeline. Ids 0 and 11 (`META_PRINCIPLE_IDS`) are meta sections skipped during annotation and scenario generation.

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
