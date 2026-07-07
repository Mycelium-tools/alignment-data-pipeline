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
outputs/            generated data (tracked in git, one directory per run)
evals/              scoring scripts and rubric
```

---

## Constitution

Two source files, kept separate and joined in memory by `shared/constitution_loader.py`:

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare section-by-section reading, with one `## ` header per section (16 sections; the 3 meta sections are skipped for scenario generation).

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
| 1 | `step1_segment.py` | Parses constitution into 10 principle sections, annotates each |
| 2 | `step2_scenarios.py` | Imports MANTA scenarios + generates additional frontier cases |
| 3 | `step3_draft_prompt.py` | Drafts realistic user messages (skipped for MANTA rows) |
| 4 | `step4_refine_prompt.py` | Naturalizes user messages (skipped for MANTA rows) |
| 5 | `step5_generate_response.py` | Generates draft responses under 4 operator-style injection types |
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

The judge is a blind, rubric-as-data LLM panel that scores corpus records; pass/fail
gates and consensus are computed in code, never by the judge model.

- `rubric_dad_v1.yaml` / `rubric_sdf_v1.yaml` — the rubrics (dimensions, anchors,
  posture classes, aggregation config). Edit these, not the prompts.
- `judge.py` / `judge_sdf.py` — the engines (prompt rendering, provider dispatch,
  verdict parsing, aggregation).
- `score_dad.py` — scores a DAD corpus with a judge panel. Writes
  `judge/<rubric_version>/verdicts.jsonl` + `summary.json` next to the corpus, plus
  the exact judge prompt each row used (`prompt_<hash>.txt`, referenced by
  `prompt_md5`). `--retry-errors` re-judges rows that previously failed.
- `report_dad.py` — renders saved verdicts into a single `report.html`: each record's
  conversation side by side with the judge's review, searchable, pass/fail filter,
  same-scenario variants diffed against their baseline.
- `adversarial.py` + `adversarial_cases.yaml` — the blindspot suite: same welfare
  issue, one axis mutated; checks relative scores so known judge biases (verbosity,
  fabricated specificity, species/substrate swaps...) can't pass unnoticed.

### Judge API keys

Judges default to Gemini (`gemini-3.1-pro-preview`); the Anthropic path also works
(`--judges claude-...` uses your `ANTHROPIC_API_KEY`). For Gemini, put one of these
in `.env`:

```bash
# Option A — Google AI Studio key (free tier ~20 requests/day/model; paid tier needs billing)
GEMINI_API_KEY=...

# Option B — Vertex AI, bills a Google Cloud project (free-trial credits apply)
VERTEX_PROJECT=your-project-id
# then authenticate once:  gcloud auth application-default login
# (or set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON with the Vertex AI User role)
```

**Panels can mix providers.** Set every key you have in `.env` and a judge panel can combine
`gemini-*` and `claude-*` models in a single run — each model routes to its own provider's key
and the verdicts are pooled into one consensus. A model whose key is missing simply errors while
the rest of the panel still scores, so you can plug in all your keys and judge with all of them
at once.

### Running the judge

```bash
python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl   # judge a corpus
python evals/report_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl  # render report.html
python evals/adversarial.py                                                   # blindspot suite
```

Or use the **Judge** page in the run viewer (below) — pick a record, edit the rubric
live, run the panel, and diff verdicts across rubric edits without touching the CLI.

---

## Setup

Install the dependencies into a virtual environment so they stay isolated from your system Python. (This isn't optional on recent macOS/Linux — a plain `pip install` is blocked by default.)

### Clone the repo
Open your terminal app and `cd` to a directory where you want the repo (i.e. `cd ~/projects`), then run:
```bash
git clone https://github.com/Mycelium-tools/alignment-data-pipeline.git
cd alignment-data-pipeline
```

### Create a virtual environment and install dependencies
```bash
python3.12 -m venv .venv       # or python3, if that's already 3.12+
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # then add your ANTHROPIC_API_KEY
```

> **Activate it every time.** The virtual environment only applies to the terminal where you ran `source .venv/bin/activate`. Open a new terminal and you'll need to activate again.

---

## Running the unit tests

The unit test suite is fully offline — it never calls the Anthropic API, needs no API key, and costs nothing. It finishes in a couple of seconds, so run it freely (and always after making functional changes; CI runs it on every PR as the required `smoke` check).

```bash
pytest                              # full suite, from the repo root
pytest tests/test_dad_steps.py      # one module
pytest -k checkpoint                # tests matching a keyword
pytest -x                           # stop at the first failure
```

Expected result: all tests pass, in well under a minute, with no network access. Three safety layers guarantee the API is never hit (pytest-socket blocks all sockets, every test gets a fake `ANTHROPIC_API_KEY`, and the API seam is replaced with a guard that raises) — so a real key in your `.env` is never used by tests. Test outputs go to temp directories; the repo's `outputs/` tree is untouched.

See the Testing section in `CLAUDE.md` for how the suite is structured and how to write tests for new stages.

---

## Quick test run

Start with the SDF pipeline — it has no external dependencies and finishes in a few minutes.

**1. Check your config.yaml is at small scale** (these are the defaults):

```yaml
sdf:
  document_types_count: 3
  subtypes_per_type: 2
  documents_per_subtype: 1
```

This produces 6 documents and costs roughly $0.05–0.15.

**2. Run the SDF pipeline:**

```bash
source .venv/bin/activate
python sdf_pipeline/run.py --config config.yaml
```

You'll see progress printed per layer with a running cost after each. Final output lands in `outputs/sdf/latest/final/sdf_corpus.jsonl`.

**3. Browse the output:**

Open `viewer.html` in a browser (double-click it), then drag-and-drop `outputs/sdf/latest/final/sdf_corpus.jsonl` onto the drop zone.

**4. Test the DAD pipeline** — reduce `scenarios_per_principle` first or it will make hundreds of API calls:

```yaml
dad:
  scenarios_per_principle: 1   # default is 10; set to 1-2 for a test
```

Then run:

```bash
python dad_pipeline/run.py --config config.yaml
```

With 1 scenario per principle (10 principles) and 4 injection types, this is roughly 120 API calls — about $1–2. Final output is `outputs/dad/latest/final/dad_corpus.jsonl`.

> **MANTA CSV is optional.** The DAD pipeline imports pre-built user messages from a MANTA CSV (`../manta_project/manta_questions_1090.csv`). If the file doesn't exist, that import is silently skipped and the pipeline generates all scenarios from scratch.

**5. Score the outputs:**

```bash
python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl
python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl
```

---

## Resuming interrupted runs

All pipeline steps checkpoint after every API call. Resume from any layer/step:

```bash
python sdf_pipeline/run.py --config config.yaml --resume --layer 3
python dad_pipeline/run.py --config config.yaml --resume --step 5
```

Running cost is tracked in each run's `cost_log.jsonl` and printed after each layer/step (see "Run organization" below).

## Run Viewer

A Streamlit app for browsing runs, their output documents, and the exact prompts that produced them:

```bash
streamlit run viewer/app.py
```

Three pages:

- **Document lineage** (default) — pick a run, click a document: the final text, then every stage with the rendered prompt side-by-side with the output it produced, including before/after diffs at the rewrite stages (SDF layer 4, DAD step 6).
- **Compare runs** — diff the prompt templates between two runs next to matched outputs, to attribute output changes to prompt changes.
- **Run list** — every run of both pipelines with label, model, counts, pass rate, and cost; click a run for its manifest details.

To make this possible, every new run snapshots `prompts/<pipeline>/` and `constitution/` into `runs/<run_id>/inputs/` at creation (~100KB of text), and `--resume` reads templates from that snapshot — so a run's prompts stay exactly reproducible even after the repo's templates change. The viewer re-renders prompts from the snapshot plus the variables stored in the stage outputs. Runs made before this feature are reconstructed from their manifest's git commit and badged "reconstructed" (with a warning if the tree was dirty at run time).

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
