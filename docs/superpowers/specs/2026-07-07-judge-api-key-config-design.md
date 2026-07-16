# Judge API-key configuration — consistency (docs-only)

**Date:** 2026-07-07
**Status:** design approved (docs-only scope)

## Problem

The repo has exactly one documented "plug in your API" path: copy `.env.example` → `.env`,
set `ANTHROPIC_API_KEY`. `shared/api.py` reads it centrally (`load_dotenv()` + `init()`) and
every pipeline call (`call_claude`) uses it.

The judge (`evals/judge.py`) introduced a second provider — Gemini/Vertex — read ad-hoc from
`GEMINI_API_KEY` / `VERTEX_PROJECT` / `GOOGLE_API_KEY` / `GOOGLE_APPLICATION_CREDENTIALS`.
Those variables appear in **no** `.env.example` and **no** README, so a new user who set only
`ANTHROPIC_API_KEY` and opened the judge (default panel `gemini-3.1-pro-preview`) gets nothing,
with no hint where to put a Gemini key.

## What already works (do NOT rebuild)

- **All keys can coexist.** Env vars are independent; `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  and `VERTEX_PROJECT` in the same `.env` all load. Nothing rejects having them all set.
- **Judge panels are already multi-provider.** `judge.call_model` dispatches per model by
  prefix (`gemini-*` → Gemini/Vertex, else → `api.call_claude`), so a panel like
  `["gemini-3.1-pro-preview", "claude-haiku-4-5", "claude-sonnet-5"]` routes each judge to its
  own provider/key in one run and computes consensus across them. If one provider's key is
  missing, only that model errors (`judge_record` catches per-model) — the rest still score.

The only gap is **discoverability + documentation**, not capability.

## Non-goals

- No concurrency / parallel panel execution (would edit `evals/judge.py::panel_judge`, the
  shared engine — out of scope, coordinate separately if wanted later).
- No moving Gemini/Vertex code into `shared/api.py` (internal tidiness, invisible to users).
- No behavior change to any judge or pipeline call.

## Changes

1. **`.env.example`** — add the judge provider keys alongside `ANTHROPIC_API_KEY`, same style:
   - `GEMINI_API_KEY=` (AI Studio key; the default judge provider)
   - commented `# VERTEX_PROJECT=` (route Gemini judges through Vertex AI billing instead)
   - commented `# GOOGLE_APPLICATION_CREDENTIALS=` (service-account JSON path, required by the
     Vertex path)
   Each with a one-line comment on what it's for.
   *(This file is permission-blocked for the assistant — the exact lines are handed to the user
   to paste.)*

2. **`README.md`** — one unified "plug in your key" story:
   - Setup: note the pipeline uses `ANTHROPIC_API_KEY`; the judge can use Anthropic
     (`claude-*` judges, same key) or Gemini (`GEMINI_API_KEY`) / Vertex.
   - Evals → Judge: document that a panel may mix providers freely, each model uses its own
     provider's key, and a missing key only disables that one model.

3. **`viewer/ui_pages/judge_batch.py`** — a short caption on the judge-panel multiselect noting
   panels can mix providers (Claude + Gemini) and each routes to its own key. (Our file.)

## Files touched

- `.env.example` (user pastes)
- `README.md` (shared, doc-only; also edited on `main` — minor merge resolution expected)
- `viewer/ui_pages/judge_batch.py` (ours)

## Verification

- Viewer still renders the judge page and the batch panel with no errors.
- A mixed-provider panel (`gemini-*` + `claude-*`) is selectable and, with both keys set, each
  model returns a verdict; with one key unset, only that model shows an error.
- README section renders and names every key the repo reads.
