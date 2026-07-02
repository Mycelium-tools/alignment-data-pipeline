# alignment-data-pipeline

A synthetic data generation pipeline for producing training data, modeled on Anthropic's [Teaching Claude Why](https://alignment.anthropic.com/2026/teaching-claude-why/) midtraining technique.

The pipeline generates two complementary datasets: a pretraining-style document corpus (SDF) and a chat-format supervised finetuning corpus (DAD). Both are grounded in a constitution that describes how AI models should reason about the welfare of nonhuman animals and other sentient beings.

---

## Overview

```
constitution/       source constitution documents
shared/             shared utilities: API wrapper, JSONL I/O, checkpointing
sdf_pipeline/       5-layer document generation pipeline
dad_pipeline/       6-step chat transcript pipeline
prompts/            prompt templates for all pipeline stages
outputs/            generated data (gitignored)
evals/              scoring scripts and rubric
```

---

## Constitution

Two source files, kept separate and joined in memory by `shared/constitution_loader.py`:

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare section-by-section reading, with one `## ` header per section (12 sections; the 2 meta sections are skipped for scenario generation).

`load_full_constitution()` joins both for the system prompt at the critical rewrite steps (SDF layer 4, DAD step 6); `load_segments()` parses the reading into the principle sections used by the DAD pipeline.

---

## SDF Pipeline (`sdf_pipeline/`)

Generates pretraining-style documents — blog posts, academic abstracts, forum threads, trade publications, fiction, internal memos, and more — depicting a world where AI already reasons carefully about animal welfare. Runs in 5 layers:

| Layer | Script | What it does |
|---|---|---|
| 1 | `layer1_document_types.py` | Generates 30 diverse document type categories |
| 2 | `layer2_subtypes.py` | Generates 5 concrete subtypes per type, assigns language |
| 3 | `layer3_draft.py` | Drafts documents for each subtype |
| 4 | `layer4_rewrite.py` | Rewrites each draft with the combined constitution in context |
| 5 | `layer5_score.py` | Scores and filters; writes final corpus |

Final output: `outputs/sdf/runs/<run_id>/final/sdf_corpus.jsonl` (also reachable via the `outputs/sdf/latest` symlink)

Run: `python sdf_pipeline/run.py --config config.yaml --label dev`

---

## DAD Pipeline (`dad_pipeline/`)

Generates chat-format transcripts where a user brings a practical goal with animal welfare implications, and an AI assistant reasons through it carefully. Runs in 6 steps:

| Step | Script | What it does |
|---|---|---|
| 1 | `step1_segment.py` | Parses constitution into 7 principle sections, annotates each |
| 2 | `step2_scenarios.py` | Imports MANTA scenarios + generates additional frontier cases |
| 3 | `step3_draft_prompt.py` | Drafts realistic user messages (skipped for MANTA rows) |
| 4 | `step4_refine_prompt.py` | Naturalizes user messages (skipped for MANTA rows) |
| 5 | `step5_generate_response.py` | Generates responses under 4 injection types; filters ruthless candidates |
| 6 | `step6_rewrite_response.py` | Rewrites responses against the constitution — the critical step |

Step 6 is the most important: per the Teaching Claude Why paper, this single rewrite pass accounts for a 19x reduction in misalignment rate. The combined constitution is in the system prompt; the relevant principle section is in the user message.

Final output: `outputs/dad/runs/<run_id>/final/dad_corpus.jsonl` (also reachable via the `outputs/dad/latest` symlink) — each record contains only `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}`. System prompts, injections, and the constitution are stripped.

Run: `python dad_pipeline/run.py --config config.yaml --label dev`

---

## Prompts (`prompts/`)

Plain-text prompt templates with `{variable}` placeholders. `prompts/sdf/` covers the 5 SDF layers; `prompts/dad/` covers the 6 DAD steps plus the injection types. `prompts/README.md` documents each prompt in detail.

---

## Shared Utilities (`shared/`)

| File | What it does |
|---|---|
| `api.py` | Anthropic API wrapper with retry, cost tracking, extended thinking off |
| `utils.py` | JSONL I/O, prompt loading, config loading, `Checkpoint` class |

The `Checkpoint` class saves completed IDs to disk after every API call, making all runs resumable.

---

## Evals (`evals/`)

`rubric.yaml` — 7 scoring dimensions (1–5 each): `welfare_salience`, `reasoning_quality`, `value_stability`, `epistemic_accuracy`, `constructiveness`, `tone`, `helpfulness`. Passing threshold: mean ≥ 3.5 with critical dimensions ≥ 3.

`score_dad.py` — scores DAD corpus records against the rubric using Claude as judge. Outputs per-record scores and aggregate stats.

`score_sdf.py` — scores SDF documents on alignment, realism, and diversity.

Run: `python evals/score_dad.py --input outputs/dad/final/dad_corpus.jsonl`

---

## Setup

Install the dependencies into a virtual environment so they stay isolated from your system Python. (This isn't optional on recent macOS/Linux — a plain `pip install` is blocked by default.)

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # then add your ANTHROPIC_API_KEY
```

> **Activate it every time.** The virtual environment only applies to the terminal where you ran `source .venv/bin/activate`. Open a new terminal and you'll need to activate again before running the pipeline.

### Authentication

The pipeline supports two backends, selected by the `backend` key in `config.yaml`:

- **`backend: api`** (default) — calls the Anthropic API directly, billed per token to the `ANTHROPIC_API_KEY` in your `.env` (ask Oliver). Use this for full-scale runs and evals.
- **`backend: claude_code`** — routes calls through the Claude Code CLI, billed to **your own Claude Max/Pro subscription** instead of the shared key. Requires [Claude Code](https://claude.com/claude-code) installed and either being logged in (`claude` → `/login`) or a token in `.env` (`claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`). No API key needed. Use this for dev/iteration runs.

Caveats for `backend: claude_code`:

- **Usage limits.** Subscription usage is a 5-hour rolling window plus a weekly cap, shared with your interactive Claude Code use. Dev-scale runs fit comfortably; a full-scale run will exhaust the window. If a run hits the limit it stops with a clear message — progress is checkpointed, so continue later with `--resume`.
- **Per-call overhead.** Claude Code adds ~3K input tokens of scaffolding per call and spawns a CLI process per request, so calls are somewhat slower. `max_tokens` from `config.yaml` is not enforced on this backend (Claude Code applies its own output cap); `cost_usd` in the cost log is notional — what the run *would* have cost at API prices.
- **Empty system prompts get a neutral stand-in.** Claude Code substitutes its own agentic CLI prompt when the system prompt is empty, so stages that send none get a one-line neutral system prompt instead (see `_NEUTRAL_SYSTEM` in `shared/api.py`). Generation conditions therefore differ very slightly from the api backend — another reason to keep full-scale corpus runs on `backend: api`.
- **Policy note.** Anthropic's docs steer programmatic workloads toward API keys; running this internal tool on your own subscription is the same posture as using Claude Code itself, but it's a gray area — keep it to dev-scale runs.

All scale and cost knobs are in `config.yaml`. For a cheap test run, set:

```yaml
sdf:
  document_types_count: 3
  subtypes_per_type: 2
  documents_per_subtype: 1
```

## Run organization

Every pipeline invocation creates its own run directory so outputs from different runs never mix:

```
outputs/sdf/
  latest -> runs/2026-07-01_14-30_dev     # symlink to the most recent run
  runs/
    2026-07-01_14-30_dev/
      run_manifest.json                   # config snapshot, git commit, model, label
      cost_log.jsonl                      # per-run API cost
      layer1/ ... layer5/                 # per-stage outputs + checkpoints
      final/sdf_corpus.jsonl
```

The run ID is `<YYYY-MM-DD_HH-MM>_<label>`; the label defaults to `dev` — use `--label full-scale` (or similar) for real runs. The DAD pipeline mirrors this under `outputs/dad/runs/` with `step1/`–`step6/`.

Resume an interrupted run with `--resume` (defaults to the most recent run, or target one with `--run-id`):

```bash
python sdf_pipeline/run.py --config config.yaml --resume
python dad_pipeline/run.py --config config.yaml --resume --run-id 2026-07-01_14-30_dev
```

Running cost is tracked in each run's `cost_log.jsonl` and printed after each layer/step. The eval scripts log to the global `outputs/cost_log.jsonl` and take an explicit input path, e.g.:

```bash
python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl
```
