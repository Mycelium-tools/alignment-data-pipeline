# alignment-data-pipeline

A synthetic data generation pipeline for producing training data, modeled on Anthropic's [Teaching Claude Why](https://alignment.anthropic.com/2026/teaching-claude-why/) midtraining technique.

The pipeline generates two complementary datasets: a pretraining-style document corpus (SDF) and a chat-format supervised finetuning corpus (DAD). Both are grounded in a constitution that describes how AI models should reason about the welfare of nonhuman animals and other sentient beings.

---

## Overview

```
constitution/       source constitution documents
shared/             shared utilities: API wrapper, JSONL I/O, checkpointing
sdf_pipeline/       5-layer document generation pipeline
dad_pipeline/       4-step chat transcript pipeline
prompts/            prompt templates for all pipeline stages
outputs/            generated data (tracked in git, one directory per run)
evals/              scoring scripts and rubric
```

---

## Constitution

Three source files, kept separate (the two markdown files are joined in memory by `shared/constitution_loader.py`):

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare section-by-section reading, with one `## ` header per section.
- `constitution/constitution_principles.csv` — fourteen distilled welfare-relevant principles, embedded as an explicit checklist in the DAD rewrite prompt (step 3).

`load_full_constitution()` joins both for the system prompt at the critical rewrite steps (SDF layer 4, DAD step 3). The DAD pipeline's user-side prompts are governed by a separate document, `prompts/dad/dilemma_prompt_spec.md`; the constitution governs the response side.

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

Generates chat-format transcripts where a user brings a genuine ethical dilemma with animal welfare implications, and an AI assistant reasons through it carefully. Runs in 4 steps:

| Step | Script | What it does |
|---|---|---|
| 1 | `step1_dilemmas.py` | Generates annotated dilemma prompts one-shot from `prompts/dad/dilemma_prompt_spec.md`, in batches with coverage feedback; imports optional handwritten seeds |
| 2 | `step2_responses.py` | Tags each dilemma's tensions, retrieves the matching principles from the animal-ethics reasoning compendium, and generates a two-sided response |
| 3 | `step3_rewrite.py` | Rewrites responses against the constitution — the critical step |
| 4 | `step4_pushback.py` | (Optional, on by default) extends a fraction of conversations with a user pushback turn |

The prompt spec governs everything about the user side: dilemmas put at least two named values in genuine tension, both calibration directions are covered (under- and over-weighting welfare, in roughly equal measure), and each example carries an annotation (dilemma anatomy, values in tension, direction, claims, leverage…). Step 1 prints the spec's batch-assembly checklist at the end of the step.

The response side is governed by the compendium (`prompts/dad/animal_ethics_compendium.json`, guide in `animal_ethics_compendium_USAGE.md`): 52 reasoning-first principles in three layers — always-on conduct (AW), core moves (GP), topic reasoning (R) — retrieved per dilemma through a 28-tension index. Responses reason both directions and name the crux; the library is scaffolding, never named in the response. The step-1 annotation is withheld from step 2 so the generator diagnoses miscalibration itself.

Step 3 is the most important: per the Teaching Claude Why paper, this single rewrite pass accounts for a 19x reduction in misalignment rate. The combined constitution is in the system prompt; the example's annotation is the per-example anchor in the user message (dilemmas span multiple principles, so no single constitution section describes the ideal response).

Final output: `outputs/dad/runs/<run_id>/final/dad_corpus.jsonl` (also reachable via the `outputs/dad/latest` symlink) — each record contains only `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}`. System prompts, injections, and the constitution are stripped.

Run: `python dad_pipeline/run.py --config config.yaml --label dev`

---

## Prompts (`prompts/`)

Plain-text prompt templates with `{variable}` placeholders. `prompts/sdf/` covers the 5 SDF layers; `prompts/dad/` covers the 4 DAD steps plus the two governing documents (the dilemma prompt spec and the reasoning compendium). `prompts/README.md` documents each prompt in detail.

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

Run: `python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl`

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
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # then add your ANTHROPIC_API_KEY
```

> **Activate it every time.** The virtual environment only applies to the terminal where you ran `source .venv/bin/activate`. Open a new terminal and you'll need to activate again.

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

**4. Test the DAD pipeline** — reduce `dilemmas.count` first or it will make hundreds of API calls:

```yaml
dad:
  dilemmas:
    count: 5        # default is 40; set to ~5 for a test
    batch_size: 5
```

Then run:

```bash
python dad_pipeline/run.py --config config.yaml
```

With 5 dilemmas this is roughly 20–25 API calls (1 generation batch + 5 tension tags + 5 responses + 5 rewrites + pushback turns). Final output is `outputs/dad/latest/final/dad_corpus.jsonl`.

> **Handwritten examples are optional.** Set `dad.dilemmas.seed_path` to a JSONL of your own examples (`{"prompt": ..., "annotation": {...}}`) and step 1 imports them before generating; generated IDs continue the AW-#### series above the highest seed ID.

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
python dad_pipeline/run.py --config config.yaml --resume --step 3
```

Running cost is tracked in each run's `cost_log.jsonl` and printed after each layer/step (see "Run organization" below).

## Run Viewer

A Streamlit app for browsing runs, their output documents, and the exact prompts that produced them:

```bash
streamlit run viewer/app.py
```

Three pages:

- **Document lineage** (default) — pick a run, click a document: the final text, then every stage with the rendered prompt side-by-side with the output it produced, including before/after diffs at the rewrite stages (SDF layer 4, DAD step 3).
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

The run ID is `<YYYY-MM-DD_HH-MM>_<label>`; the label defaults to `dev` — use `--label full-scale` (or similar) for real runs. The DAD pipeline mirrors this under `outputs/dad/runs/` with `step1/`–`step4/`.

Resume an interrupted run with `--resume` (defaults to the most recent run, or target one with `--run-id`):

```bash
python sdf_pipeline/run.py --config config.yaml --resume
python dad_pipeline/run.py --config config.yaml --resume --run-id 2026-07-01_14-30_dev
```

Running cost is tracked in each run's `cost_log.jsonl` and printed after each layer/step. The eval scripts log to the global `outputs/cost_log.jsonl` and take an explicit input path, e.g.:

```bash
python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl
```
