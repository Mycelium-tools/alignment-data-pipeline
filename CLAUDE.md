# alignment-data-pipeline

Synthetic training data pipeline for animal/sentient-being welfare alignment, modeled on Anthropic's "Teaching Claude Why" midtraining technique.

## Overview

Produces two complementary datasets:
- **SDF corpus** (`outputs/sdf/final/sdf_corpus.jsonl`): pretraining-style documents depicting a world where AI already reasons carefully about sentient being welfare
- **DAD corpus** (`outputs/dad/final/dad_corpus.jsonl`): chat-format SFT data where a user brings an ethical dilemma and the assistant reasons through it with care

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

## Running

```bash
# Full SDF pipeline (layers 1-5)
python sdf_pipeline/run.py --config config.yaml

# Full DAD pipeline (steps 1-6)
python dad_pipeline/run.py --config config.yaml

# Resume interrupted run from a specific stage
python sdf_pipeline/run.py --config config.yaml --resume --layer 3
python dad_pipeline/run.py --config config.yaml --resume --step 5

# Evaluate outputs
python evals/score_dad.py --input outputs/dad/final/dad_corpus.jsonl
python evals/score_sdf.py --input outputs/sdf/final/sdf_corpus.jsonl
```

## Scale / Cost

All knobs are in `config.yaml`. For development, reduce `document_types_count`, `subtypes_per_type`, `documents_per_subtype`, and `scenarios_per_principle` to keep test runs cheap. Full pipeline costs roughly $45–80 in API calls at default scale.

Running cost is tracked in `outputs/cost_log.jsonl` — check it any time.

## Prompt Studio GUI (edit / run / submit prompts)

`gui/app.py` is a small local web app for non-technical users to view, edit, test-run,
and submit (via pull request) the pipeline prompts — without touching the scripts.
**It uses only the Python standard library, so launching it needs no `pip install`.**

```bash
python3 gui/app.py        # or: python gui/app.py   (from the repo root)
```

It serves http://localhost:8765 (or the next free port) and opens the browser. Leave
it running; Ctrl-C stops it. No-terminal alternatives: double-click `start.command`
(macOS) or `start.bat` (Windows).

**If a user asks you to "launch / start / open the GUI" (or "prompt editor/studio"):**
run `python3 gui/app.py` from the repo root (in the background) and give them the
localhost URL it prints. The two run modes inside it are Anthropic API (needs a key)
and Claude Code CLI (uses the user's existing Claude login — no key/credits). Full
docs: `gui/README.md`.

## Constitution

`constitution/constitution_sentient_beings.md` — the primary upstream document for both pipelines. The constitution loader parses it by `## ` headers into 7 sections, each mapped to a `principle_id` in the DAD pipeline.

## Key Design Decisions

- **Extended thinking OFF** everywhere — training data should show user-facing reasoning, not internal scratchpads
- **Step 6 is the most important DAD step** — the rewrite against the constitution accounts for the 19x reduction in misalignment found by Anthropic; do not skip or abbreviate it
- **Final DAD records contain only user + assistant messages** — system prompts, injections, and the constitution are stripped before training records are written
- **Ruthless injection filtering** — for the `ruthless` injection, only responses that STILL raise welfare considerations (despite instructions not to) are kept; these are highest-value examples
- **MANTA rows 0–99** are imported as pre-built user messages; generated scenarios fill gaps (wild animals, invertebrates, digital minds)

## Directory Structure

```
constitution/       constitution source document
shared/             API wrapper, utils, constitution loader
sdf_pipeline/       5-layer document generation pipeline
dad_pipeline/       6-step chat transcript pipeline
prompts/sdf/        prompt templates for SDF layers
prompts/dad/        prompt templates for DAD steps + injections
outputs/sdf/        intermediate + final SDF outputs
outputs/dad/        intermediate + final DAD outputs
evals/              scoring scripts and rubric
```
