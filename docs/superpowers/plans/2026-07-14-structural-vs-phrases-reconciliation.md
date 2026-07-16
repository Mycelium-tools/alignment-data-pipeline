# Reconciliation plan — structural analyzer vs. remote's phrases/diversity-axes work

**Status:** proposed, no git actions taken. My feature is committed locally (`f93021b`); remote `arda/dad-judge-rubric` is 172 commits ahead with overlapping work; nothing pushed.

## The two lines of work

- **Local (mine, `f93021b`):** a first-class `structural` holistic analyzer + a reusable `texts` input on `AnalysisContext`, surfaced on the Run-diversity Analyze button. Signals: opening/closing moves, considerations scaffold, markdown formatting, length/truncation, phrase recurrence.
- **Remote (`29d222f` "Three diversity axes + phrase-repetition check"):** `evals/holistic/phrases.py` (`phrase_report`) wired **directly into the viewer page**, plus 3 new categorical extraction axes in `dad_axes.yaml`, plus supporting changes to `extract.py`/`fields.py`/`bundle.py` and committed run artifacts.

## Guiding principle

Keep the better version of each overlapping piece; add only what's genuinely new; don't duplicate.

## Keep / Drop / Add

| Piece | Decision | Why |
|---|---|---|
| Remote `phrases.py` (`phrase_report`) | **KEEP** | More polished than my `recurring()`: curated lexicon, apostrophe folding, clean doc-frequency verdict |
| My `structural.recurring()` + `STOCK_PHRASES` | **DROP** | Superseded by `phrases.py` |
| My `closing_moves()` | **ADD** | No remote equivalent |
| My `scaffold_shape()` | **ADD** | No remote equivalent (the acknowledge→considerations→recommend arc) |
| My `formatting()` | **ADD** | No remote equivalent (markdown/bold density) |
| My `length_stats()` | **ADD** | No remote equivalent (length spread + truncation) |
| My `opening_moves()` | **ADD (decide)** | Remote's `openings_dad.py` is a standalone CLI, not on the Analyze button; mine adds openings there. Overlap is by surface, not code. **Open decision below.** |
| My `texts` input + `structural` analyzer plumbing | **ADD** | Reusable architecture; the remote computes phrases in-page without it |
| 3 new categorical axes (remote `dad_axes.yaml`) | **KEEP** (untouched) | Orthogonal — categorical lane, not structural |

## Net result

`structural.py` keeps: `assistant_turns`, `first_sentence`, `last_sentence`, `_move_shapes`, `_verdict`, `opening_moves`, `closing_moves`, `scaffold_shape`, `formatting`, `length_stats`, and the opener/closer/scaffold/markdown constants. It **loses** `recurring()` and `STOCK_PHRASES`. The `structural` analyzer's returned dict drops its `"recurring"` key. My `recurring`-specific test is removed.

## File-by-file reconciliation (against remote tip)

1. **`evals/holistic/structural.py`** — NEW file, applies clean. Remove `recurring()`, `STOCK_PHRASES`, and the `import` of anything only it used. (No conflict — remote has no such file.)
2. **`evals/holistic/analyzers.py`** — remote left this at the old 4-tuple `INPUTS`, so my changes (add `"texts"`, `AnalysisContext.texts`, `available` branch, `_structural` fn, register in `default_analyzers`) apply **clean**. Edit: drop the `"recurring"` key from `_structural`'s return dict.
3. **`evals/holistic/pipeline.py`** — CONFLICT (remote +4 lines). Merge: keep remote's changes AND add the `texts` derivation in `run()` + the `texts` param on `analyze()`. Small, mechanical.
4. **`evals/dad_axes.yaml`** — CONFLICT (remote +32: 3 new axes). Merge: keep remote's new axes; add `structural` to the `analysis.analyzers` list (their list is unchanged from base since phrases isn't a registered analyzer).
5. **`viewer/ui_pages/run_diversity.py`** — CONFLICT (remote added a phrases section). Merge: keep remote's phrases section; add my structural section **without** a phrase/recurring row (phrases already has its own section). Place my section adjacent to theirs. Re-verify placement against the remote's current page structure (drift/synthesis anchors may have moved).
6. **My tests** (`test_holistic_structural.py`, `test_holistic_analyzers.py`, `test_holistic_pipeline.py`, `test_holistic_cli.py`, `test_holistic_config.py`) — apply mostly clean (remote didn't touch them). Remove the `recurring` assertions. Re-check the `inputs_present` assertions against the remote's pipeline (their +4 may change ordering).

## Mechanics (avoids the untracked-outputs clash)

The main working tree can't rebase because the remote committed `outputs/dad/runs/...` artifacts that exist here as untracked files. Work in a **fresh worktree checked out at the remote tip** instead, where those outputs are tracked:

1. `git worktree add ../adp-reconcile origin/arda/dad-judge-rubric -b arda/structural-merge`
2. Re-apply the KEEP/ADD changes above (cherry-pick `f93021b` then edit out `recurring`, or hand-apply the trimmed set).
3. Resolve conflicts in files 3–5. Run `pytest` (offline) green.
4. Live-verify the Run-diversity page renders both the phrases section and my structural section.
5. Fast-forward push `arda/structural-merge` → `arda/dad-judge-rubric` (now = remote tip + my additive commits).
6. Remove the worktree. The local drift-stream uncommitted work in the main tree is never touched.

## Open decisions for you

- **A. `opening_moves` — keep on the Analyze button, or defer to `openings_dad.py`?** Recommend keep (different surface: the CLI is for multi-sample opener analysis; the analyzer is the at-a-glance page verdict).
- **B. Re-home `phrases.py` onto the `texts` analyzer?** Optional. Converting `phrase_report` into a registered analyzer (using my `texts` input) makes phrase-repetition + my signals all first-class analyzers with one render path, instead of one in-page + one analyzer. More work; more consistent. If you skip it, the page shows two sections (theirs + mine).
- **C. `dad_axes.yaml` `analysis.analyzers`** — confirm `structural` is the only addition; leave the 3 new axes and any other remote edits intact.

## What I have NOT done

No worktree, no cherry-pick, no merge, no push. My `f93021b` sits on the local branch; the foreign drift-stream work sits uncommitted in the main tree, restored to its original state.
