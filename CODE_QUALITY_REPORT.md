# Code Quality Report — alignment-data-pipeline

**Date:** 2026-07-10 · **Scope:** full repo at commit `cf8d91e` (all source, tests, CI, docs; committed `outputs/` scanned for hygiene only)
**Purpose:** pre-delivery quality assessment with prioritized recommendations, ahead of handing the pipeline to a frontier lab.

## How this audit was produced

1. **Mechanical baseline** — ruff (broad rule set), `ruff format --check`, mypy (lenient), `pytest --cov`, vulture, dependency review. All report-only; nothing in the repo was modified.
2. **Seven charter reviews** run as parallel agents, each with a specific brief: money-path correctness, LLM-output parsing, failure-handling parity, duplication/structure, the `step1_dilemmas.py` god-file, test-suite quality, and delivery-readiness/process.
3. **Adversarial verification** — every high/medium finding was re-checked by independent agents instructed to refute it against the current code; refuted findings were dropped.
4. **Synthesis** into this report.

**Verification legend** (every finding below carries one):

| Mark | Meaning |
|---|---|
| ✓✓ | Confirmed by independent adversarial verification |
| ✓c | Confirmed with corrections (details amended by the verifier; corrected wording used here) |
| ✓m | Verified manually by the lead reviewer reading the cited code (used where the automated verifier was lost to a usage-limit outage mid-run) |
| ○ | Its own verifier was lost to the outage, but an independently **confirmed** finding from a different charter establishes the same defect |
| △ | Unverified (low/info severity — reported as observed, treat as probable-not-proven) |

Sixteen verification agents failed on an account usage limit partway through; no finding below rests solely on an unverified claim unless marked △. A handful of findings the verifiers *refuted* or corrected were dropped or amended — e.g. the initially-reported "69 mypy errors" is environment-dependent (45–81 depending on installed stubs), and the layer-5 sentinel claim was narrowed to exclude prose-wrapped JSON (which `extract_json` handles fine).

---

## Executive summary

**This repo is in substantially better shape than "vibe-coded by non-engineers" suggests.** Baseline hygiene is strong: near-universal docstrings that explain rationale rather than restate signatures, near-universal type hints, pathlib and f-strings throughout, no TODO markers or commented-out code, essentially zero dead code (vulture found one unused variable), clean secret hygiene (`.env` never tracked; all 231 committed output files free of keys and personal paths), and a genuinely good offline test suite — 295 tests with a four-layer network guard, behavior-level assertions, and disciplined checkpoint/resume tests across most stages. The Claude-review + CLAUDE.md process has clearly worked as a quality mechanism.

The problems are **specific and clustered**, not pervasive:

1. **The two pipelines were written to different robustness standards.** DAD steps 2–3 and the pref pipeline are exemplary fail-closed engineering (stop_reason gates, retry ladders, failure logs, skip-without-checkpoint so `--resume` retries). The older SDF layers predate that discipline: **no SDF layer checks `stop_reason`**, and layer 4 — the rewrite the code itself credits with a 19× effect on misalignment rate — silently substitutes the *un-rewritten draft* on any parse failure or truncation, checkpoints it, and ships it toward the training corpus. CLAUDE.md's claim that "every generation call rejects truncated output" is currently true only for DAD.
2. **The persistence primitives are not crash-safe.** `Checkpoint` rewrites its JSON in place and `load_jsonl` tolerates no partial trailing line, so the recovery path for the most common failure (an interrupted run) can itself brick `--resume` — and the natural operator fix re-bills a whole stage.
3. **LLM-output parsing is implemented seven times with conflicting semantics.** Only SDF layers 1/2/5 use the well-tested `utils.extract_json`; the hardening lessons paid for at one site (e.g. `strict=False` for temperature-1 control characters, learned in step 2) never propagated to the others.
4. **Test coverage is inverted relative to risk in two places.** The paid LLM-judge eval scripts (`score_sdf.py`, `score_dad.py`) — which produce the quality numbers that would accompany a delivery — are at 0% coverage and permanently checkpoint parse failures as zero scores. And `step1_dilemmas.py`'s untested 16% is *exactly* its money-path fallbacks (the JSON salvage machinery and batch retry loop).
5. **There is no static-analysis tooling at all.** No linter, formatter, type checker, or coverage measurement anywhere; CI gates on `compileall` + pytest only, and the Claude reviewer is explicitly told to skip style — so no layer of the process ever pushes back on lint-class defects.
6. **Delivery packaging is thin.** Not pip-installable (hence a `sys.path.insert` hack in 23 files), floors-only requirements with no lockfile (`numpy` missing entirely — it arrives transitively), and a few README claims that misdescribe the alignment-critical wiring.

The right framing for remediation: **harmonize everything up to the standard the best code in this repo already sets.** Almost every Tier-1 fix below is "copy the pattern that already exists in DAD step 2/3." Estimated total effort for Tier 1: a few contributor-days.

---

## Tier 1 — Fix before delivery

Defects that can silently corrupt training data, lose or re-bill paid API work, or misstate the quality evidence a lab would rely on. Ordered by impact.

### 1.1 Layer 4 rewrite fails open: un-rewritten drafts enter the corpus, unretryable — ✓✓ (×2 charters) + ✓m
**`sdf_pipeline/layer4_rewrite.py:43-61,80` · severity HIGH · effort S**
The call omits `return_stop_reason=True` (max_tokens=6000, same as layer 3's draft budget). If the `<improved_document>` tag is missing or empty — exactly what truncation or a refusal produces — the code silently sets `rewritten = draft["content"]` and **checkpoints the record** (line 80), so `--resume` never retries. A truncated rewrite therefore ships the original draft into layer 5, where drafts routinely score ≥7 and enter `sdf_corpus.jsonl` having skipped the pass the module's own comment calls "the pipeline's most leverage-heavy call (TCW's ablation: removing it cost 19x on misalignment rate)". The only trace is a note buried in `rewrites.jsonl`.
**Fix:** copy `dad_pipeline/step3_rewrite.py:58-89` — request stop_reason, retry once at a doubled cap, and on continued failure log to `rewrite_failures.jsonl` and skip **without** `mark_done`. Flip the two pinning tests (`test_missing_tags_keeps_original_draft`, `test_empty_rewrite_keeps_original_draft`) deliberately, per CLAUDE.md's spec-first rule.

### 1.2 Layer 5 checkpoints score-parse failures, permanently discarding paid documents; the {5,5,5} sentinel is threshold-coupled — ✓✓ + ✓c
**`sdf_pipeline/layer5_score.py:79-82,111-121` · severity HIGH · effort M**
On a `JSONDecodeError` the doc gets fabricated scores of 5/5/5, is appended and `mark_done`'d — so `--resume` never re-scores it, and the paid layer-3 draft + layer-4 rewrite for that doc are permanently lost (5 < the current threshold of 7). Verifier correction: prose-wrapped JSON is *not* a trigger (extract_json handles it); truncated/malformed/absent JSON is — and stop_reason is never checked here either. Worse, the fail-closed behavior is a coincidence of configuration: `min_score_threshold: 7` lives in `config.yaml:13` with no comment linking it to the sentinel. A dev run with the threshold lowered to 5 flips the same path **fail-open** — parse-failure docs enter the corpus unscored. A list-shaped judge response also crashes the layer (`scores.get` on a list; only JSONDecodeError is caught).
**Fix:** bounded retry (the step-2a `MAX_SCOPE_ATTEMPTS` pattern), raw failures to `score_failures.jsonl`, skip without append/mark_done on final failure; validate `isinstance(scores, dict)`; if any sentinel must remain for legacy records, make it zeros.

### 1.3 Checkpoint and JSONL persistence are not crash-safe: a kill mid-write bricks `--resume` — ✓m
**`shared/utils.py:288-291,296-304,60-65` · severity HIGH · effort S**
`Checkpoint.mark_done` rewrites the whole JSON file in place (`open(path, "w")` — no temp-file + `os.replace`); `Checkpoint.__init__` does a bare `json.load`; `load_jsonl` raises on a partial trailing line, which is precisely what a crash mid-`append_jsonl` leaves. So a $50 run killed at the wrong instant makes the *next* `--resume` crash before any API call — and the natural operator recovery (delete `_checkpoint.json`) re-bills the whole stage and, in layers 2–4 (see 1.7), appends duplicates beside the survivors.
**Fix:** atomic write (`.tmp` + `os.replace`) in `mark_done`; catch decode errors in `__init__` and rebuild from the empty set with a warning (safe: every stage writes output before marking); tolerate exactly one malformed **final** line in `load_jsonl` with a warning. All three are small and independently testable.

### 1.4 One failed step-1c refine discards the whole batch's paid 1b + sibling refine work — ✓✓ + ○
**`dad_pipeline/step1_dilemmas.py:756-815` · severity HIGH · effort M**
Step 1 is the only stage that defers all persistence to end-of-batch: refine results collect in memory, and record assembly/`append_jsonl` happen in a separate loop afterwards. An exception from any one refine (rate-limit storm exhausting tenacity, or the claude_code backend's deliberately-unretried `UsageLimitExceeded`) propagates before anything is written — `--resume` then re-bills the 16k-token 1b batch call *and* every sibling refine that had already succeeded. Related fail-open (✓✓): a refine that returns unusable output silently keeps the cheap-model 1b draft with no retry, no failure log, and no marker on the record — despite `config.yaml` labeling 1c the "load-bearing rewrite".
**Fix:** wrap the refine worker in try/except → log + return None so the existing keep-draft fallback applies, with a 3-strike abort mirroring the 1b loop; merge the two loops so each record is appended as its refine completes; add a bounded retry to `refine_draft` and a `refine_failed: true` marker if keep-the-draft remains the last resort.

### 1.5 Step-1 JSON parsers reject the failure mode step 2 already learned to tolerate (`strict=False`) — ✓c + ○
**`dad_pipeline/step1_dilemmas.py:564,578,584,600` · severity HIGH · effort S**
`step2_responses.py` passes `strict=False` with a comment naming literal newlines inside JSON strings as "the way a prose-heavy JSON object at temperature 1.0 most often goes invalid" — and the test suite calls it "the historical cause of silently empty scopes". Step 1's four `json.loads` calls (including the salvage machinery whose whole job is rescuing these payloads) all use strict defaults, so the documented most-common failure defeats every fallback in sequence and re-bills 16k-token batch calls; three consecutive occurrences kill the run.
**Fix:** add `strict=False` at the four sites (+ `json.JSONDecoder(strict=False)` in `extract_json`), with a control-character regression test per parser. Strictly a relaxation of control-character handling — cannot admit wrong-shaped data.

### 1.6 Layer 3 never checks stop_reason: silent corpus shrinkage, and the untagged fallback can admit a truncated fragment — ✓✓ + ○
**`sdf_pipeline/layer3_draft.py:143-164,185` · severity MEDIUM · effort M**
A max_tokens cutoff silently drops the trailing document(s) of a batch — the subtype is checkpointed done with fewer docs than configured, unrecorded. Worse, when *no* complete `<document>` block exists, the whole truncated output is trimmed "to the last complete sentence" and becomes a draft — an essay that stops after its setup paragraph reads as complete and can pass layers 4–5 into the corpus.
**Fix:** request stop_reason; on `max_tokens` keep the closed-tag docs, never take the untagged fallback, log the shortfall to `draft_failures.jsonl`, and print when `len(docs) < count`.

### 1.7 Layers 2–4 trust only the checkpoint for done-ness: a crash in the append→mark window duplicates records and re-bills on resume — ✓✓ + ○
**`sdf_pipeline/layer4_rewrite.py:30` (also layer2:41, layer3:108) · severity MEDIUM · effort S**
Layer 5, DAD steps 2–3, and pref all cross-check the output file as well as the checkpoint; layers 2–4 don't, so a crash between append and mark_done means `--resume` re-bills the item and appends a second record with the same id — layer 5 then scores both (more paid calls), and with near-dup culling disabled the document can enter the corpus twice.
**Fix:** one line in layer 4 (exclude doc_ids present in `existing`, exactly like layer 5); dedupe-on-load for layers 2–3. Subsumed long-term by the `resumable_stage` helper (Tier 2.2).

### 1.8 The paid eval judges persist unretryable zero scores and are 0% tested — the delivered quality numbers can be silently wrong — ✓✓ (×2 charters) + ○
**`evals/score_sdf.py:61-75`, `evals/score_dad.py:92-107` · severity HIGH · effort M**
Both scripts hand-roll fence-stripping + bare `json.loads` (not the tolerant `extract_json` the pipelines adopted after a live failure in PR #59), default parse failures to **zero scores**, then append + `mark_done` — so a re-run never repairs them and every aggregate is dragged down silently. A judge returning a quoted-string score bricks the summary on every subsequent invocation. These scripts compute the corpus-quality evidence a lab would see; they are also the only pipeline-adjacent code with zero tests.
**Fix:** parse with `extract_json`; coerce dimension scores with `int(...)`; skip-without-checkpoint on failure; report "N unparsed" beside the aggregates; extract the loop into a testable `run()` and add the standard test triad.

### 1.9 `--run-id` without `--resume` is silently ignored: mints a fresh run and re-bills the pipeline — ✓✓
**`sdf_pipeline/run.py:39-43` (same in dad:47-51, pref:103-107) · severity MEDIUM · effort S**
A contributor resuming an interrupted full-scale run who forgets `--resume` gets a brand-new run directory, a repointed `latest` symlink, and a from-scratch re-bill — with no warning. Also: sdf's `--layer` accepts any int (`--layer 6` runs nothing and reports $0.0000 success) while dad's `--step` validates choices.
**Fix:** `parser.error("--run-id requires --resume")` in all three; give `--layer` `choices=range(1,6)`.

### 1.10 Pref pipeline re-reads the live prompts file on `--resume`: an edited file silently mispairs arm responses — ✓m
**`pref_pipeline/run.py:94-101,43` · severity MEDIUM · effort S**
Arms are frozen into the run dir precisely so resume replays them; the prompts are not, and prompt ids fall back to positional `row{i:04d}`. Edit or regenerate the prompts file while a pair is deferred, and resume pairs arm A's cached response to the *old* text with arm B's fresh response to the *new* text — raters then blind-compare responses to two different prompts, and `preferences.jsonl` (potential DPO data) is silently wrong.
**Fix:** freeze resolved prompts to `run_dir/inputs/prompts.jsonl` at creation and load from there on resume; or store a text hash per cached arm response and refuse on mismatch.

---

## Tier 2 — Structural improvements

Worth doing before or shortly after delivery; each reduces the maintenance burden the receiving lab inherits. All have concrete designs in the audit worth preserving in the implementing PRs.

### 2.1 Consolidate the seven parsing implementations — ✓✓ (×2 charters)
Seven parsers across six files, with three conflicting salvage philosophies (`extract_json` refuses fragments of broken containers; step 1's `_salvage_objects` deliberately harvests them; step 2 brace-slices greedily). The `strict=False` history proves fixes don't propagate across copies. **Design:** extend `shared/utils.extract_json` with an `expect='array'|'object'` parameter (also fixes the unvalidated-shape crashes at `layer1_document_types.py:47`, `layer5_score.py:93` — ✓m) and `strict=False`; move `_salvage_objects` to shared as `salvage_json_objects()` with its contract documented (fragment-harvest is safe only where the caller re-requests missing items by id — step 1b is the sole qualifying site); migrate call sites in small PRs, each carrying a fixture test from the old site's known failure mode. Effort M.

### 2.2 Extract a `resumable_stage()` helper — ✓✓
The load-existing / filter-pending / append / mark-done idiom is hand-rolled seven times and has already diverged on the safety-relevant detail in 1.7. A single helper in `shared/utils.py` (pending = not in done-set ∪ checkpoint; zip with `parallel_map` `strict=True`; main-thread persist in input order; persist returns the checkpoint ids to mark, empty = retry-on-resume) gives every stage layer-5's idempotence and step-3's retry contract by construction. Adopt stage-by-stage; existing tests keep passing. Effort M.

### 2.3 Extract the triplicated orchestrator setup — ✓c
`sdf/dad/pref run.py` repeat a ~35-line setup block (PIPELINE_OUTPUT_ROOT, resume-vs-create, backend warning, `api.init`) plus four argparse flags; cross-cutting fixes have already had to land three times (the UTF-8 sweep) and have already drifted (1.9). Extract **only** the setup (`utils.setup_run()` + `add_common_args()`); leave stage gating and pipeline-specific wiring in place — forcing those into a framework is where churn risk exceeds benefit for this contributor base. Effort M.

### 2.4 Make the repo an installable package — ✓✓ + ✓c
No `[project]` table; `sys.path.insert(0, ...)` in 23 files (already drifted: `ui_pages/` needs three `.parent`s); `pip install .` fails outright for a lab trying to vendor the pipeline; a forgotten path-hack in a new file passes CI (pytest uses `pythonpath="."`) and fails only at runtime. **Fix:** minimal `[build-system]`/`[project]` metadata (concrete sketch in the audit), `pip install -e .` in setup docs + CI, then delete the path hacks (library modules first). Two-PR sequence keeps every state green. Effort M.

### 2.5 Split `step1_dilemmas.py` (819 lines, six concerns, highest churn) — ✓✓
`run()` alone is 182 lines at C901=24. Deck edits — the thing non-engineers touch most — currently share a file with the batch-retry money loop, so every spec tweak forces re-reasoning about re-billing safety. **Verified PR sequence:** (1) characterization tests for the salvage/retry paths *first* (see 2.6); (2) `shared/jsonparse.py` (folds into 2.1); (3) move decks + sampling verbatim to `dad_pipeline/scenario_deck.py` with re-exports so tests and `viewer/rendering.py` stay green; (4) move coverage checklist; leaving step1 as orchestration only. Effort L, but each PR is small.

### 2.6 Close the risk-inverted test gaps — ✓c + ✓✓
The untested 16% of step 1 is exactly `_salvage_objects`, every parser fallback branch, the unusable-batch retry/3-strike abort, and the refine keep-draft path (coverage lines confirm precisely — objective). Layer 4 has no resume test (✓m: layers 1–3 do; a checkpoint-keying regression in the most expensive stage would re-bill invisibly). `audit_sdf.py` — the stated defense against the haiku-test2 corpus-collapse failure mode — is 25% covered, with six of eight checks untested. The audit contains concrete test recipes for each. Effort M total.

### 2.7 Small hardening batch (one PR) — △/✓m
Ruff-flagged seeds verified benign-but-fragile (✓m): default-bind the layer-2 wave note (`lambda dt, note=note:`), add `strict=True` to the four zips. Coerce `workers` once in `parallel_map` (a quoted `workers: "8"` in YAML currently crashes SDF but not DAD — △). Shuffle before truncating in `_deck` so small runs don't always draw the same domains (△). Count parse failures in the audit prevalence rater instead of counting them as "no defect" (△). Warn on config drift at `--resume` beyond the backend key (△). Fix or delete the documented-but-unread `refined` field in pref (✓m: no producer currently emits it — make the docs and code agree either way).

---

## Tier 3 — Process and tooling

The repo currently has **zero** static analysis. Given the contributor base, adopt autofix-first tooling: machines fix what they can; humans only see what matters.

### 3.1 Ruff (lint + format) with an autofix-first rollout — ✓✓
`[tool.ruff]` with `select = ["E","F","W","B","C4","SIM","DTZ"]`, `ignore = ["E501"]` (formatter owns wrapping), deliberately excluding complexity rules (wrong gate for non-engineers). One mechanical `ruff check --fix && ruff format` commit (45/52 files reformat), its SHA in `.git-blame-ignore-revs`, then a `lint` job in CI. Today's real catches beyond style: the B023 capture, four B905 zips, three naive datetimes, two unused variables.

### 3.2 Coverage floor in CI — ✓✓ (×2 charters)
`pytest-cov` with `--cov-fail-under=74` over `shared, sdf_pipeline, dad_pipeline, pref_pipeline, evals` (the non-viewer tree sits at ≈76–78% today, so it passes immediately), omitting `viewer/*` and `pref_pipeline/rate.py` (UI shells — the logic-extraction pattern that keeps them thin is worth codifying in CLAUDE.md). Ratchet upward as Tier-1/2.6 tests land (~85 within reach); never lower without team agreement.

### 3.3 Gradual mypy — ✓c
Error counts are environment-dependent (45–81); the highest-value fix is root-cause, not config: `@overload` on `call_claude` keyed on `return_stop_reason` (Literal[True] → tuple), which erases ~20 errors at zero runtime change and makes the "flipped the flag, forgot to unpack" bug — which crashes *after* the paid call and before checkpointing — a hard type error. Then a deliberately narrow `[tool.mypy]` that is green on day one, expanded per-module.

### 3.4 Pin the dependency environment — ✓✓
Floors-only requirements, no lockfile, `numpy` missing (arrives transitively via pandas), `tqdm`/`jsonlines` listed but never imported. Neither the lab nor future CI can reconstruct the environment the committed example runs were produced with. **Fix:** `requirements.in` (edited by humans; add numpy, drop the two unused) compiled to a fully-pinned `requirements.txt` via `uv pip compile`; optionally record installed versions into `run_manifest.json` so each run self-documents.

### 3.5 Teach the Claude reviewer the repo's own PR policies — ✓✓
The review prompt asks for bugs/security/CLAUDE.md violations and explicitly skips style — but never instructs it to check the repo's three hard PR rules (tests accompany pipeline changes; "How to test" section present; template placeholder changes update `test_prompts_render.py`). Since `claude[bot]` approval satisfies branch protection, a same-repo PR can merge with zero human review and zero policy check. Append a policy block to the prompt (concrete wording in the audit); pin the action to a SHA instead of the mutable `@v1` tag.

### 3.6 One doc-accuracy pass before delivery — ✓✓ + △
`README.md:31` misstates the alignment-critical wiring: it says `load_full_constitution()` (constitution + sentient-beings reading) feeds SDF layers 4–5, but the code sends `load_constitution_with_principles()` (constitution + distilled principles CSV) — a lab engineer would build a wrong model of exactly the corpus-shaping stages, and the loader's own docstring contradicts the README. Also: dead `config.yaml` output-path keys; the root-level `sdf-notebook-port-report.md` still says "uncommitted, awaiting review" (long since merged); "Ask Oliver" as the API-key instruction dead-ends outside the original team. Suggested policy line for CLAUDE.md: README claims about which text reaches which API call must change in the same PR as the call.

---

## What is already good (keep it)

Worth stating plainly in a report a lab will read:

- **Money-path engineering is deliberate**: output-before-checkpoint ordering everywhere, `parallel_map`'s in-order/main-thread-write contract is real and correctly documented, and DAD steps 2–3 + pref are exemplary fail-closed designs (the Tier-1 fixes are mostly "copy these").
- **The test harness is unusually strong**: four independent layers guarantee no test can touch the network or spend money; `stub_claude` fails loudly on concurrency misuse; constitution expectations are derived, not hardcoded; brittleness is low.
- **Secret and output hygiene is clean**: `.env` never tracked; committed run outputs scanned free of keys, usernames, and absolute paths.
- **`claude-code-review.yml` is well-engineered** (verdict-verification step defeats false-greens; restricted tool allowlist) — it just needs the policy block (3.5).
- **No dead code, no commented-out blocks, no TODO debt**; legacy paths are labeled and quarantined in the viewer.
- **Docstrings explain *why***, at a density most professionally-maintained repos don't reach.

---

## Appendix A — Mechanical baseline numbers (2026-07-10)

| Measure | Result |
|---|---|
| Source size | ~6,840 LOC (33 files) + 3,319 test LOC (295 tests, all offline, ~2 s) |
| Ruff (broad ruleset) | 541 findings — 430 line-length; 13 C901 complexity; 1 B023; 4 B905; 3 DTZ005; 2 F841; 1 F401 |
| `ruff format --check` | 45 of 52 files would reformat |
| mypy (lenient, this env) | 69 errors (env-dependent 45–81); top: arg-type 22, union-attr 19, attr-defined 10 |
| Coverage (total) | 58% — bimodal: pipelines 84–100%, `shared/` 95–100%; `score_sdf`/`score_dad`/`rate.py`/viewer UI 0%, `audit_sdf` 25%, `viewer/loader` 38% |
| Non-viewer coverage | ≈76% (basis for the 74% CI floor) |
| Vulture (dead code) | 1 unused variable (`viewer/loader.py:75`) |
| Dependencies | floors-only, no lockfile; `numpy` missing; `tqdm`, `jsonlines` unused |
| Largest/highest-churn files | `step1_dilemmas.py` 819 LOC / 22 commits; `api.py` 502 / 19; `audit_sdf.py` 523; `rendering.py` 474 |

## Appendix B — Full findings ledger

52 findings from 7 charters; verdicts from the adversarial pass: 21 confirmed, 6 confirmed-with-corrections, 25 unverified (16 verifier agents lost to a usage-limit outage; low/info findings were unverified by design). Every unverified high/medium finding used in this report was either corroborated by an independently confirmed finding from another charter (○) or manually re-verified against the code (✓m). Findings not individually discussed above (all low/info, △): layers 1–2 lack an in-run parse retry (crash discards in-flight sibling calls); step-3/2b truncation gates test only `max_tokens` rather than rejecting all non-`end_turn` stop reasons; the SDF e2e test dispatcher keys on `max_tokens` values instead of prompt markers; `--resume` silently applies live-config model/knob changes (manifest then misdescribes the run); stale root-level working reports.

Full machine-readable findings (titles, evidence, failure scenarios, recommendations, verifier notes) are preserved as `findings.json` alongside the audit workflow's journal in `~/.claude/projects/-Users-declan-Projects-alignment-data-pipeline--claude-worktrees-code-quality/00008bca-87eb-47f0-935e-004ea49fee99/subagents/workflows/wf_3e2c7be7-0ed/`; the implementing PRs for Tiers 1–2 should lift the per-finding recommendations, which include concrete APIs, test recipes, and PR sequencing.
