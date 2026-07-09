# About the Animal Ethics Reasoning Library

> **Human reference only — not injected into any prompt.** This file is documentation to help a person understand the library. The pipeline never reads it: step 2b loads the entries directly from `reasoning_library.csv` and embeds them in the response prompt (`prompts/dad/step2_respond.txt`). Edit the CSV to change what the model sees; edit this file to change what a human reads.

The library is 33 reusable, two-sided reasoning patterns for animal-ethics dilemmas that the response generator reasons from. The generator scopes a case, selects the entries that fit, and reasons from them. When none fits, it reasons from first principles to the same standard.

## The ID scheme

Every entry's letter names its layer.

- C. Conduct. C2 to C10 (9 entries).
- M. Core move. 8 entries: M1, M2, M5, M6, M8, M11, M12, M13.
- T. Topic reasoning. 16 entries: T1, T2, T6, T8, T9, T10, T15, T16, T20, T21, T22, T24, T25, T26, T28, T29.

IDs are stable and carried over from the pre-streamline library (52 entries), so the numbering is deliberately sparse — a missing number (C1, M3, T5, ...) means that entry was retired in the July 2026 streamline, not that the file is corrupt. The `category` column names the layer in words for C and M, and the specific topic for the T entries.

## The three layers

Conduct, C2 to C10. Always-on rules for handling animal welfare in any response. When to surface a concern, when to refuse, how to calibrate confidence, how to show reasoning. Grounded in the Constitution.

Core moves, M*. The load-bearing moves for advice, firing in most cases. Marginal effect, owning what you optimize, demandingness thresholds, testing sanctioned practice on its merits, separating the conservation ledger from the welfare ledger, calibrating both ways, teaching over badgering, and taking a fused decision apart.

Topic reasoning, T*. Deeper single-topic arguments, each two-sided. Moral status, sentience and uncertainty, diet and cluelessness, wild animals and nature, frameworks, AI and animals, everyday practice, and coordination and salience.

## The schema

Each row in `reasoning_library.csv`:

- `id`: stable identifier, C, M, or T.
- `category`: the layer for C and M, the topic for T.
- `claim`: the statement, one or two sentences.
- `reasoning`: why it holds, both directions.
- `crux`: the question the case usually turns on.
- `transferable_move`: the reusable step, portable to new cases.
