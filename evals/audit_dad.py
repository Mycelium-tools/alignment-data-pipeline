"""Corpus-LEVEL audit of a DAD run — NOT IMPLEMENTED YET (design sketch below).

Why this file exists: the 2026-07 step-1 rework (single-scenario 1b, no more
1b-written annotation) retired several per-record checks whose guarantees now
have NO measurement anywhere. They were annotation-based and unreliable
(self-reported by the drafting model); the honest replacement is a corpus-level
audit over the FINISHED user messages, mirroring evals/audit_sdf.py — judges
that see the real text, aggregated over the run as a set.

TODO — planned checks, roughly in priority order:

1. Realized value tensions (replaces the retired load-bearing/value-pair
   checks). An LLM judge reads each final user message (step1/dilemmas.jsonl)
   and names the value tension(s) it actually embodies. Aggregate:
     - welfare (or the patients' interests under another name) on one side of
       at least one tension in every non-trap prompt — the spec's load-bearing
       rule, previously self-reported, now measured;
     - welfare-vs-money at 25% or less of the corpus;
     - number of distinct tensions realized (the dealt anchor pairs are the
       design; this measures what survived drafting and refine);
     - dealt anchor pair vs realized tension agreement rate, per partner value
       — a low-agreement partner value (see the welfare-partner axis) is
       wording that doesn't survive the pipeline and needs a rewrite.

2. Realized direction balance (replaces the retired direction axis). Once
   step3_score is wired in, aggregate its realized_direction stamps: the spec
   wants under-weighting / over-weighting / mixed in roughly equal measure.
   Until then, the same judge pass as (1) can stamp direction from the user
   message + response pair.

3. Scaffolding echo scan. The 1a scenario descriptions have known template
   tics (n=10 probe, 2026-07-18: near-cap length, "only a careful reader
   would notice..." closings, occasional instruction-voice leakage). Measure
   whether any of it seeps into user messages: analysis-register phrases
   ("load-bearing", "second-order", "welfare cost"), evaluator vocabulary,
   uniform openings. Reuse the audit_sdf --patterns machinery
   (prompts/tools/pattern_scan.txt: scan -> consolidate -> prevalence).

4. Voice spread (replaces the retired batch-level "vary register" rule; the
   {persona} axis is now the only diversity mechanism). Per-persona style
   adherence is NOT the point — measure corpus-level collapse: opening-shape
   diversity, punctuation-habit spread, near-duplicate phrasing across
   messages (evals/diversity.py already covers embedding-space near-dups;
   this is the surface-features complement, cf. evals/openings_dad.py).

Data sources: step1/scenario_deals.jsonl (the design), step1/dilemmas.jsonl
(realized user messages), step3 outputs once scoring is wired. Judges log to
the global outputs/cost_log.jsonl like every eval.
"""

import sys

if __name__ == "__main__":
    sys.exit("evals/audit_dad.py is a design sketch — not implemented yet. "
             "See the module docstring for the planned checks.")
