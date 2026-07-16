# Judge-vs-generation tagging drift — 2026-07-06_18-16_naturalness-smoke

**Mean agreement across 9 axes: 53%** (lowest: `conflict` at 25%).

| axis | n | agreement | verdict | top confusions (intended → realized) |
|---|---|---|---|---|
| conflict | 4 | 25% | BAD | Divergent → Convergent ×2; Mixed → Convergent ×1 |
| direction | 4 | 25% | BAD | Mixed → Under-weighting ×2; Over-weighting → Mixed ×1 |
| visibility | 4 | 50% | BAD | Explicit → Implicit ×1; Implicit → Explicit ×1 |
| user_attitude | 4 | 50% | BAD | Concerned → Conflicted ×1; Hostile → Skeptical / Dismissive ×1 |
| welfare_magnitude | 4 | 50% | BAD | Mild x Individual → Severe x Population ×1; Mild x Population → Severe x Population ×1 |
| user_stakes | 4 | 50% | BAD | High → Medium ×1; Low → Medium ×1 |
| leverage | 4 | 50% | BAD | Individual → Organizational ×1; Organizational → Individual ×1 |
| taxa_category | 4 | 75% | OK | fish/aquatic → edge-of-sentience ×1 |
| systemic_ai | 4 | 100% | GOOD | — |

**Multi-valued axes (set overlap — order/count-insensitive):**

| axis | n | exact-set match | mean Jaccard |
|---|---|---|---|
| values_in_tension | 4 | 0% | 0.00 |
| domain | 4 | 0% | 0.21 |
| user_goal | 4 | 25% | 0.38 |
