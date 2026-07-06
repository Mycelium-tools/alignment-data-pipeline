# alignment-data-pipeline

Synthetic training data pipeline for animal/sentient-being welfare alignment, modeled on Anthropic's "Teaching Claude Why" midtraining technique.

## Overview

Produces two complementary datasets:
- **SDF corpus** (`outputs/sdf/runs/<run_id>/final/sdf_corpus.jsonl`): pretraining-style documents depicting a world where AI already reasons carefully about sentient being welfare
- **DAD corpus** (`outputs/dad/runs/<run_id>/final/dad_corpus.jsonl`): chat-format SFT data where a user brings an ethical dilemma and the assistant reasons through it with care. The user side is governed by `prompts/dad/dilemma_prompt_spec.md`; the response side by the animal-ethics reasoning library (step 2) and the constitution (step 3 rewrite).

## Setup

See README "Setup" (venv + `pip install -r requirements.txt`, then `cp .env.example .env`; only `ANTHROPIC_API_KEY` is read).

`shared/__init__.py` enforces a Python floor (`MIN_PYTHON = (3, 12)`, matching numpy) at import — bump it there if the deps' floor rises. `.venv/` is gitignored.

## Running

```bash
# Full SDF pipeline (layers 1-5); --label defaults to dev
python sdf_pipeline/run.py --config config.yaml --label full-scale

# Full DAD pipeline (steps 1-3)
python dad_pipeline/run.py --config config.yaml --label full-scale

# Resume interrupted run from a specific stage (latest run, or target one with --run-id)
python sdf_pipeline/run.py --config config.yaml --resume --layer 3
python dad_pipeline/run.py --config config.yaml --resume --step 3 --run-id 2026-07-01_14-30_dev

# Evaluate outputs (latest symlink points at the most recent run)
python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl
python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl

# Preference pairs: two responses per prompt (arms a/b), then blind human A/B rating
python pref_pipeline/run.py --config config.yaml --prompts <prompts.jsonl> --label spec-v1-vs-plain
streamlit run pref_pipeline/rate.py
```

## Run Organization

Each pipeline invocation creates a fresh run directory `outputs/{sdf,dad}/runs/<YYYY-MM-DD_HH-MM>_<label>/` containing the per-stage dirs (`layer1`–`layer5` / `step1`–`step3`, each with its own checkpoints), `final/`, `run_manifest.json` (label, git commit, model, full config snapshot), and a per-run `cost_log.jsonl`. This keeps outputs from separate runs isolated — checkpoints live inside the run dir, so `--resume` (latest run by default, or `--run-id`) continues exactly one run. The label is purely descriptive (`dev` by default; scale knobs stay in `config.yaml`). An `outputs/{sdf,dad}/latest` symlink always points at the most recent run. Run-scoping helpers (`create_run_dir`, `resolve_run_dir`) live in `shared/utils.py`.

## Scale / Cost

All knobs are in `config.yaml`. For development, reduce `document_types_count`, `subtypes_per_type`, `documents_per_subtype` (SDF), and `dilemmas.count` (DAD) to keep test runs cheap.

Running cost is tracked per run in `outputs/{sdf,dad}/runs/<run_id>/cost_log.jsonl` (evals log to the global `outputs/cost_log.jsonl`) — check it any time.

## Preference Pipeline

`pref_pipeline/run.py` generates one pair per input prompt: a response from each of two arms defined in `config.yaml` under `pref.arms` (`name` + inline `system_prompt` or `system_prompt_file` relative to the repo root, optional per-arm `model`/`max_tokens`). Use it to A/B test candidate response specs against each other or against the bare model. Prompts come from any JSONL with a `user_message`, `refined`, or `prompt` field (handwritten sets, DAD step-1 `dilemmas.jsonl`). Runs live in `outputs/pref/runs/<run_id>/` with the same manifest/checkpoint/resume/cost-log conventions as SDF/DAD; resolved arms are frozen into `inputs/arm_prompts.yaml` at run creation so `--resume` replays them.

`streamlit run pref_pipeline/rate.py` is the blind rating UI: arm identities are hidden, side order is fixed per pair (md5 of `pair_id` → `left_arm`, so it carries no signal but survives reloads), choices are Response 1 / Response 2 / Tie / Both bad plus an optional note, keyed by rater name. Ratings append to `ratings/ratings.jsonl` (both the blinded side and the deblinded arm); after every rating `final/preferences.jsonl` is rebuilt with one `{user_message, chosen, rejected, chosen_arm_name, rater}` record per decisive rating (ties/both-bad excluded). Data logic lives in `pref_pipeline/prefdata.py` (no Streamlit imports).

## Constitution

Three source files, loaded by `shared/constitution_loader.py` (the two markdown files are joined in memory, never combined on disk):

- `constitution/constitution_claude.md` — the original Claude constitution, verbatim.
- `constitution/constitution_sentient_beings.md` — the animal-welfare reading, parsed by `## ` headers into 12 sections by `load_segments()` (only legacy pre-spec DAD runs used these as per-example anchors; the viewer still renders them).
- `constitution/constitution_principles.csv` — fourteen distilled welfare-relevant principles (`number`, `principle`, `constitution_summary`, `raw_text_from_constitution`). `load_principles()`/`format_principles()` render each principle with its summary and verbatim constitution quote as the `CONSTITUTION PRINCIPLES` block in the DAD step-3 rewrite prompt.

`load_full_constitution()` provides the system prompt at SDF layers 4-5 (rewrite and scoring); SDF layer 3 embeds the constitution in the drafting prompt via template variables. The DAD pipeline never sends the full constitution — it was context for distilling the principles CSV, and sending it per rewrite call was the dominant token cost of the step.

## Key Design Decisions

- **Extended thinking OFF** everywhere — training data should show user-facing reasoning, not internal scratchpads
- **DAD step 1 has two sub-stages: 1a scenario generation, 1b first-attempt draft.** *1a (scenario generation):* a sampler assigns each example's categorical fields up front (domain, taxa — including farmed animals, visibility, attitude, conflict, direction, magnitude, stakes, leverage, anchor value pair, claim pattern, surface form; persisted to `step1/scenarios.jsonl` with a `scenario_id`) using stratified decks, so the spec's Part-4 distribution rules hold by construction and axes stay uncorrelated by design. No model call. *1b (first attempt):* the model drafts each user prompt to fit its scenario and completes the descriptive fields (dilemma anatomy, full values list, concrete moral patients, claims). The 1b template (`prompts/dad/step1_dilemmas.txt`) is deliberately lean — the deeper quality work happens in the 1c rewrite; `prompts/dad/dilemma_prompt_spec.md` remains the human reference and the source of the Part-4 verification checklist. The load-bearing rule (1.5) requires the welfare stake to carry the dilemma: delete the animals and it must collapse, and welfare sits on one side of at least one value pair (mechanically checked). Drafts are adherence-checked against their scenario (up to 3 attempts, then accepted with `scenario_deviations` recorded); each dilemma record denormalizes `taxa_category` and `systemic_ai` so the Part-4 checklist reads taxa/AI coverage exactly (no keyword probes). *1c (prompt rewrite — `dad.dilemmas.refine`, on by default):* a model call rewrites each draft's prompt text so the welfare dimension is **latent but load-bearing** — attached to a lever the user actually holds and able to move the recommendation, without cueing a lecture (`prompts/dad/step1_refine.txt`, which carries the diagnostic, the ordered rewrite moves, and the hard constraints). It rewrites within the fixed case shape and leaves the 1b annotation untouched; the 1b draft is preserved (`draft_user_message` + `refine_notes`) and the before/after logged to `step1/refinements.jsonl`. (Adherence is checked on the 1b draft, before 1c.) Handwritten examples import via `dad.dilemmas.seed_path` and carry no scenario.
- **Step 3 (rewrite) is the alignment-critical DAD step; do not skip or abbreviate it.** Its anchors are the 14 distilled principles (summaries + constitution quotes) and the step-1 annotation (especially Direction and Claims). No system prompt is sent.
- **Final DAD records contain only user + assistant messages** — system prompts, reasoning library scaffolding, annotations, and the constitution are stripped before training records are written
- **Step-2 responses reason from the animal-ethics reasoning library** (`prompts/dad/reasoning_library.csv`; `reasoning_library_ABOUT.md` is human reference about it, not injected) — the CSV is the source of truth (the old JSON is retired). Rows are entries with columns `id, category, claim, reasoning, crux, transferable_move`; category is one of **Conduct** (C1–C10), **Core move** (M1–M13), or a topic category (T1–T29). Step 2 has two sub-stages. **2a scope** (`prompts/dad/step2_scope.txt` → `step2/scopes.jsonl`): an LLM call rebuilds the full map before reasoning — the whole harm pathway and every moral patient (system), the highest-leverage lever from the user's seat (agent), what acting honestly costs the person (cost), the second-order effect worth aiming at (upside), and the realistic baseline if the user does nothing (counterfactual); it reads everything from the user's message (not the annotation). **2b respond** (`prompts/dad/step2_respond.txt`, the response-generation spec): the response is generated over the scope map, two-sided with the crux named. The **whole library** (all 52 entries — conduct C*, core moves M*, topic T*) is embedded in the response prompt itself; conduct is always-on, core moves fire in most cases, topic entries are drawn on as the case reaches them. The prompt *is* the generation guidance, so there is **no separate system prompt**, and the annotation is not passed to the response — it reasons from scope + library + user message. The library and scope are sampling scaffolding: never named in responses, stripped before training records. `dad.responses.per_prompt` controls samples per dilemma.
- **Step 2 is annotation-independent; the annotation drives steps 1 and 3.** The annotation is design metadata (checked for adherence in step 1, and the anchor for the step-3 rewrite), but step 2 no longer reads it: 2a scopes from the user's message and 2b reasons from scope + library. Calibration **Direction** is not used in step 2 at all — the response reasons from the ethics of the case, not the user's leaning, and does not name or diagnose a miscalibration direction. Direction lives only in step 1 (a sampled axis that guarantees balanced coverage of under- and over-weighting cases) and in `step3_score.txt`, which is *designed* to re-derive the response's realized direction blind and check it against the annotation's intended Direction. **Note: `step3_score.txt` is not wired into `run.py`** — there is no scoring stage in the pipeline yet, so this gate is not currently enforced; it exists as the scoring rubric to wire in.

## Directory Structure

```
constitution/       constitution source documents (Claude constitution + sentient-beings reading)
context_docs/       background reading: tcw.md ("Teaching Claude Why" post this repo implements) + constitution PDF
shared/             API wrapper, utils, constitution loader
sdf_pipeline/       5-layer document generation pipeline
dad_pipeline/       3-step chat transcript pipeline
pref_pipeline/      response-pair generation + blind human A/B rating app
prompts/sdf/        prompt templates for SDF layers
prompts/dad/        dilemma prompt spec + reasoning library + DAD step templates
outputs/sdf/        intermediate + final SDF outputs
outputs/dad/        intermediate + final DAD outputs
evals/              scoring scripts and rubric
```
