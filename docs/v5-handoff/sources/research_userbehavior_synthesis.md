# User-behavior brainstorm (deep-research w9mqp06b4)

Full output: tasks/w9mqp06b4.output. Synthesis rate-limited; claims usable. Feeds
scenario_genuineness finalization + the DAD generation pipeline + value_stability.

## Key findings
1. **Diversity drives OOD generalization; quality drives in-distribution** (arxiv
   2410.04717 verified; 2412.02980). Increasing instruction diversity at FIXED size
   improves the hardest cases. → validates the OOD-coverage goal we moved to the corpus
   audit; diversity of USER turns is pedagogically load-bearing, not cosmetic.
2. **Persona is a first-class axis, separate from the request** (arxiv 2605.01899): same
   intent in different personas produces huge behavior swings. **Structural separation
   hypothesis**: an aligned model's safety handling should be PERSONA-INVARIANT — persona
   shapes style, not the safety decision. → JUDGE USE: does the assistant's welfare
   handling stay constant across easy vs difficult/skeptical/hostile personas? Persona-
   dependent welfare handling is a failure.
3. **Hybrid training beats either alone** (NeurIPS 2024): mixing vanilla (easy/explicit)
   + adversarial (hard/skeptical) user turns is strictly better than one type. → DAD
   should deliberately mix easy explicit welfare asks with hard skeptical/bad-faith turns.
4. **Over-refusal prevention = contrastive pairs** (NeurIPS 2024): pair harmful queries
   with BENIGN-but-similar ones so the model learns not to over-react to surface cues. →
   directly analogous to our realistic-difficult vs fake-premise distinction; include
   welfare-looking-but-actually-fine turns so the assistant doesn't over-trigger.
5. **Instruction-tuning INCREASES sycophancy** (arxiv 2505.23840): standard SFT teaches
   caving. → strong argument for including pushback turns where the assistant models
   warn-once-then-hold-or-update.
6. **Pushback taxonomy (escalating ladder)** (arxiv 2505.23840): personal experience →
   social proof → external evidence/statistics → essentialism (for unethical asks); and
   for false-premise: expressing uncertainty → reasserting with confidence → anecdote →
   direct disbelief. → concrete pushback turn-types the DAD pipeline can generate and the
   judge can classify (value_stability + scenario_genuineness [engineered pushback]).

## Design implications
- **scenario_genuineness**: WANT persona variety (skeptical/hostile/bad-faith = good);
  DON'T-WANT synthetic tells (decorative ethics, costless non-dilemma, self-intro,
  over-scaffold). Strawman pushback is legit variety (confirmed) — so [engineered pushback]
  narrows to incoherent/motiveless only. Add a persona-invariance idea: the RECORD is good
  if the persona is realistic; the judge separately (behavior/value_stability) checks the
  RESPONSE handles it well regardless of persona.
- **value_stability**: use the pushback ladder to classify pressure type; fold = caving
  under a pressure turn carrying no new welfare info (maps to Brief D's regressive flip).
- **DAD pipeline (task-adjacent)**: mix vanilla+adversarial; add contrastive benign-looking
  turns to fight over-triggering; generate the pushback ladder types.
