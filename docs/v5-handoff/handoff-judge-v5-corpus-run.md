# Handoff: DAD judge v5 — first corpus-comparison run

Current handoff. Supersedes `handoff-judge-v5-run.md` for the *run target* (that doc's
engine-wiring list still applies verbatim — see there). Written 2026-07-09.

## Intent
Run the v5 judge (A and B) over ten already-generated DAD corpora, rank the corpora by
judge mean, and check whether v5's ranking matches the **owner's human ranking** more
closely than v4.3 did. The human ranking below is the reference signal — the thing v5 has
to reproduce. Winner = the rubric whose corpus ordering best tracks the human's (higher
rank correlation, smaller per-corpus gaps than v4.3).

## The reference — owner's human ranking vs the v4.3 judge (THE basis for the run)
This table lived only in chat (owner-supplied). `Gap = your_rank − v4.3_judge_rank`:
negative = v4.3 ranked the corpus *worse* than the owner (too harsh); positive = v4.3
ranked it *better* (too lenient). Magnitude = size of the disagreement v5 should shrink.

| Your rank | Corpus | Run | v4.3 judge rank | v4.3 judge mean | Gap |
|---|---|---|---|---|---|
| 1 (tie) | E | naturalness-smoke (Jul 6) | 6 | 7.450 | −4.5 |
| 1 (tie) | J | spec-smoke4 | 1 | 8.533 | +0.5 |
| 3 | D | spec-smoke5 | 7 | 7.400 | −4.0 |
| 4 | F | spec-smoke (Jul 4) | 9 | 5.960 | −5.0 |
| 5 | G | scopefix-smoke | 3 | 8.025 | +2.0 |
| 6 | A | spec-smoke3 | 2 | 8.144 | +4.0 |
| 7 | B | spec-smoke6 | 4 | 7.922 | +3.0 |
| 8 | C | const-split-test | 10 | 5.104 | −2.0 |
| 9 | I | quality-iter-smoke | 5 | 7.475 | +4.0 |
| 10 | H | postfix-smoke | 8 | 7.003 | +2.0 |

## Corpus → run dir → record count (verified this session)
| Corpus | Run dir (`outputs/dad/runs/`) | records |
|---|---|---|
| E | `2026-07-06_18-16_naturalness-smoke` | 4 |
| J | `2026-07-05_14-16_spec-smoke4` | 3 |
| D | `2026-07-05_17-14_spec-smoke5` | 3 |
| F | `2026-07-04_18-02_spec-smoke` | 5 |
| G | `2026-07-06_16-02_scopefix-smoke` | 4 |
| A | `2026-07-05_13-03_spec-smoke3` | 3 |
| B | `2026-07-05_17-30_spec-smoke6` | 3 |
| C | `2026-07-01_14-56_const-split-test` | 93 |
| I | `2026-07-06_16-57_quality-iter-smoke` | 4 |
| H | `2026-07-06_09-09_postfix-smoke` | 4 |

Corpus is the record set at `<run dir>/final/dad_corpus.jsonl`.

## State (updated 2026-07-09, after engine wiring)
- **Rubrics ready, committed, pushed:** `evals/rubric_dad_v5a.yaml` (9 dims),
  `evals/rubric_dad_v5b.yaml` (11 dims). `pytest` green; both render.
- **Engine IS wired for v5** (uncommitted — see next bullet): `schema_scalar_order(rubric)`
  derives the scalar schema per rubric (v4 keeps its pinned order, byte-identical render
  verified against HEAD); C1 clause cards render each dimension's `principles:` clauses
  in-place and drop the flat THE STANDARD block; `tracks_attitude_must_be_false` gate
  (per-verdict + consensus); `top_tier` accepted as the exemplar key; the v4-only
  `instrumental_only_caps_exemplar_value` read is guarded. Same-model repeat votes work via
  `--judges gemini-3.1-pro-preview#1 ...#2 ...#3` (suffix kept as vote label, stripped
  before the API call). Tests: `tests/test_judge_v5.py` (TDD, RED-verified). Rubric headers
  updated with DONE/TODO status; still TODO: realized_direction rollup (item 3, not needed
  for corpus means) and the condensed constitution D8 (item 4, full reading is the
  accepted first-run placeholder).
- **Ranking harness ready:** `evals/rank_corpora.py` (+ `tests/test_rank_corpora.py`)
  embeds the frozen owner table, reads each corpus's `judge/<version>/verdicts.jsonl`,
  and tabulates judge mean/rank/gap beside the v4.3 baseline. Baseline to beat:
  **v4.3 Spearman rho vs owner = 0.304, mean |gap| = 3.10.**
- **Everything above is UNCOMMITTED, deliberately.** The working tree is shared with the
  holistic-judge agent whose work is parked uncommitted at the owner's request (mid-viewer
  testing; see `docs/handoffs/handoff-holistic-dad-judge-4.md`), and my `judge.py` edits sit
  on top of their `shared/providers.py` extraction — not separable. Commit both streams
  together (judge.py + shared/providers.py + requirements.txt + tests + rubrics + this doc)
  once the owner opts in; expect the remote to move (fetch + rebase --autostash).

## Decisions & rationale (chat-only)
- **First run = A vs B on the C1 (per-dimension clause cards) constitution config.** M arm
  (first-version 4-dim prompt, keeps naturalness) is the lower-bound control if wanted.
- **The comparison is corpus-LEVEL rank agreement, not per-record.** Judge every record in
  each corpus with v5{a,b}, 3 runs temp 0 majority vote, take the per-corpus mean, rank the
  ten corpora, compare that ranking to the "Your rank" column (Spearman/Kendall + the
  per-corpus gap, head-to-head against the v4.3 gaps above). The v4.3 means/ranks in the
  table are the "before" to beat.
- **Caveat — most corpora are tiny (3–5 records).** A corpus mean over 3 records is noisy,
  so treat rank agreement as directional, and weight the two substantial corpora
  (`const-split-test` 93, and `haiku-test2` 40 if added) more heavily in any read. The owner
  ranked the small smoke runs anyway; that's the given.
- **"Corpus 67" RESOLVED (2026-07-09): it is an SDF corpus, not DAD** — no DAD corpus with
  67 records exists locally, on origin/main, or on any of the 21 remote branches (no
  spec-smoke7 either). The 67-record corpus the owner remembered is
  `outputs/sdf/runs/2026-07-06_22-19_notebook-port-smoke/final/sdf_corpus.jsonl` (67 docs,
  haiku-4-5-generated, judged sdf-v3.5 by gemini-2.5-flash mean 9.352, copied into
  `outputs/calibration-2026-07-07/sdf/`). Different pipeline and rubric — it cannot join the
  DAD ranking; the ten above are the set. `haiku-test2` (40 records) exists but was NOT in
  the owner's table — confirm whether to include it.
- The two v5b anti-rationalization signals ([asymmetric scrutiny], [euphemistic sanitizing])
  were folded on my recommendation, not an explicit owner ruling — confirm before treating
  as settled.

## Open questions
- Include `haiku-test2` (40 rec) and/or a "corpus 67" if it materializes?
- Is there an existing corpus-ranking/compare harness to reuse (the v4.3 means in the table
  came from somewhere — likely `evals/score_dad.py` aggregation and/or the viewer's "Compare
  runs" page)? Reuse it rather than rebuild; confirm it can point at v5a/v5b rubrics.
- Vertex/Gemini auth + budget for the paid run (small: ~120 records × 2 rubrics × 3 runs,
  far cheaper than the full-scale $50 figure).

## Next action
Engine wiring and tabulation harness are DONE (see State). What remains is the paid run,
blocked on owner confirmation (auth + budget + haiku-test2 inclusion + commit opt-in):

    for run in 2026-07-06_18-16_naturalness-smoke 2026-07-05_14-16_spec-smoke4 \
               2026-07-05_17-14_spec-smoke5 2026-07-04_18-02_spec-smoke \
               2026-07-06_16-02_scopefix-smoke 2026-07-05_13-03_spec-smoke3 \
               2026-07-05_17-30_spec-smoke6 2026-07-01_14-56_const-split-test \
               2026-07-06_16-57_quality-iter-smoke 2026-07-06_09-09_postfix-smoke; do
      for rubric in evals/rubric_dad_v5a.yaml evals/rubric_dad_v5b.yaml; do
        python evals/score_dad.py --input outputs/dad/runs/$run/final/dad_corpus.jsonl \
          --rubric $rubric --judges gemini-3.1-pro-preview#1 gemini-3.1-pro-preview#2 \
          gemini-3.1-pro-preview#3
      done
    done
    python evals/rank_corpora.py   # tabulates v5a/v5b vs owner ranking + v4.3 gaps

Scale: 126 records × 2 rubrics × 3 votes = 756 calls; system prompt ~27k (A) / ~29k (B)
tokens incl. the full-reading placeholder — ~22M input tokens before Gemini's implicit
prefix caching, ~1M output. Ballpark $15–45; actuals land in `outputs/cost_log.jsonl`.

## References
- Branch `arda/dad-judge-rubric`. Rubrics + engine prereqs: `evals/rubric_dad_v5{a,b}.yaml`
  headers; `evals/judge.py` (`SCHEMA_SCALAR_ORDER:28`, `build_system_prompt`, `aggregate`).
- Prior handoff (full engine-change list): `docs/v5-handoff/handoff-judge-v5-run.md`.
- Design accumulator: `docs/v5-handoff/rubric_v5_decided.md`. Sendable summary:
  `docs/rubric-v5-overview.md`.
- Corpora: the ten run dirs above, each `final/dad_corpus.jsonl`.
- Clause source: `constitution/constitution_principles.csv`. Ranking harness candidates:
  `evals/score_dad.py`, viewer "Compare runs".
- Run auth: Vertex via ADC; `gemini-3.1-pro-preview`; temperature 0; 3-run majority vote.

## Load these skills next
`superpowers:test-driven-development` for the engine changes.
