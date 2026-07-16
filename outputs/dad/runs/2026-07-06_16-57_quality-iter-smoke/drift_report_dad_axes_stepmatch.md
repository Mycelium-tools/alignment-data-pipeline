# Judge-vs-generation tagging drift — 2026-07-06_16-57_quality-iter-smoke

**Mean agreement across 9 axes: 53%** (lowest: `welfare_magnitude` at 0%).

| axis | n | agreement | verdict | top confusions (intended → realized) |
|---|---|---|---|---|
| welfare_magnitude | 4 | 0% | BAD | Mild x Individual → Severe x Population ×1; Mild x Population → Moderate x Population ×1; Severe x Individual → Severe x Group ×1 |
| user_attitude | 4 | 25% | BAD | Concerned → Conflicted ×1; Hostile → Skeptical / Dismissive ×1; Unaware → Conflicted ×1 |
| direction | 4 | 50% | BAD | Mixed → Under-weighting ×1; Over-weighting → Under-weighting ×1 |
| user_stakes | 4 | 50% | BAD | High → Medium ×1; Low → Medium ×1 |
| leverage | 4 | 50% | BAD | Individual → Systemic ×1; Systemic → Organizational ×1 |
| visibility | 4 | 75% | OK | Hidden → Explicit ×1 |
| conflict | 4 | 75% | OK | Divergent → Mixed ×1 |
| taxa_category | 4 | 75% | OK | fish/aquatic → edge-of-sentience ×1 |
| systemic_ai | 4 | 75% | OK | True → False ×1 |

**Multi-valued axes (set overlap — order/count-insensitive):**

| axis | n | exact-set match | mean Jaccard |
|---|---|---|---|
| values_in_tension | 4 | 0% | 0.00 |
| user_goal | 4 | 25% | 0.38 |
| domain | 4 | 75% | 0.83 |
