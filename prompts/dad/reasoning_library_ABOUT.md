# About the Animal Ethics Reasoning Library

> **Human reference only — not injected into any prompt.** This file is documentation to help a person understand the library. The pipeline never reads it: step 2b loads the entries directly from `reasoning_library.csv` and embeds them in the response prompt (`prompts/dad/step2_respond.txt`). Edit the CSV to change what the model sees; edit this file to change what a human reads.
>
> **Non-normative while the design iterates.** Where this document and the CSV or templates disagree, the CSV/templates win; do not cite this document as a requirement in code review.

The library is 52 reusable, two-sided reasoning patterns for animal-ethics dilemmas that the response generator reasons from. The generator scopes a case, selects the entries that fit, and reasons from them. When none fits, it reasons from first principles to the same standard.

## The ID scheme

Every entry's letter names its layer.

- C. Conduct. C1 to C10.
- M. Core move. M1 to M13.
- T. Topic reasoning. T1 to T29.

The `category` column says the same in words, plus the specific topic for the T entries.

## The three layers

Conduct, C1 to C10. Always-on rules for handling animal welfare in any response. When to surface a concern, when to refuse, how to calibrate confidence, how to show reasoning. Grounded in the Constitution.

Core moves, M1 to M13. The load-bearing moves for advice, firing in most cases. Marginal effect, owning what you optimize, role scope, verifying welfare claims, demandingness, sanctioned practice, symbolic harm, calibrating both ways, teaching over badgering, and taking a fused decision apart.

Topic reasoning, T1 to T29. Deeper single-topic arguments, each two-sided. Moral status, sentience, diet, wild animals, offsetting, frameworks, AI and animals, everyday practice, and salience.

## The schema

Each row in `reasoning_library.csv`:

- `id`: stable identifier, C, M, or T.
- `category`: the layer for C and M, the topic for T.
- `claim`: the statement, one or two sentences.
- `reasoning`: why it holds, both directions.
- `crux`: the question the case usually turns on.
- `transferable_move`: the reusable step, portable to new cases.
