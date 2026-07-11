"""Compose layer-3 input prompts from a template and a variables file.

EXPERIMENTAL replacement for SDF layers 1-2: instead of two LLM calls
generating document types and subtypes, a combinatorial matrix of pre-written
variables is expanded deterministically. Offline, zero API calls.

Inputs
------
- Template (``prompts/sdf/matrix/template.txt``): plain text with
  ``{{variable_name}}`` slots. NOT loaded through ``shared.utils.load_prompt``
  (no ``str.format``), so literal braces are harmless.
- Variables (``prompts/sdf/matrix/variables.txt``)::

      {{varname}}  # optional description
          plain value
          0.25 :: weighted value

  Full-line ``#`` comments and blank lines are ignored anywhere. Weights are
  all-or-nothing within a variable and must sum to 1.0; an unweighted
  variable is uniform.

Two kinds of template slot:

- ``{{name}}`` — a matrix axis, filled from variables.txt.
- ``{{_name}}`` — injected by this script, never defined in variables.txt.
  Supported: ``{{_preamble}}`` (contents of ``--preamble``, default
  ``prompts/sdf/preamble.txt``).

Usage
-----
    # Dry run: matrix size, per-variable counts, three sample prompts
    python sdf_pipeline/compose_prompts.py

    # THE knob for run size: deck-sample exactly N prompts. Per-variable
    # value shares match the weights by construction (largest-remainder
    # quotas per variable, each deck shuffled, decks zipped) — no drift.
    python sdf_pipeline/compose_prompts.py --n-prompts 5000 --seed 0 --out prompts.jsonl

    # Full cartesian product (ignores weights; can be huge — for debugging)
    python sdf_pipeline/compose_prompts.py --out all_prompts.jsonl

Output records: ``{"prompt_id": ..., "variables": {...}, "prompt": ...}``
(``variables`` holds only the matrix axes, not injected slots).

Repeated combinations in a sample are allowed by design: drawing one cell
twice just means two documents from that cell (the old pipeline's
``documents_per_subtype`` > 1 was the same thing), and generation runs at
temperature 1.0. Illogical combinations are handled downstream: the template
asks the model to answer INCOHERENT rather than force a nonsense document.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / "prompts" / "sdf" / "matrix" / "template.txt"
DEFAULT_VARIABLES = REPO_ROOT / "prompts" / "sdf" / "matrix" / "variables.txt"
DEFAULT_PREAMBLE = REPO_ROOT / "prompts" / "sdf" / "preamble.txt"

PLACEHOLDER_RE = re.compile(r"\{\{(_?[A-Za-z0-9_]+)\}\}")
WEIGHT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*::\s*(.+)$")
WEIGHT_TOLERANCE = 1e-6


def parse_variables(path: Path) -> dict[str, list[tuple[str, float | None]]]:
    """Parse variables.txt into {name: [(value, weight-or-None), ...]}."""
    parsed: dict[str, list[tuple[str, float | None]]] = {}
    current: str | None = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        header = PLACEHOLDER_RE.fullmatch(line.strip().split("#")[0].strip())
        if not line.startswith((" ", "\t")):
            if header is None:
                raise ValueError(
                    f"{path.name}:{lineno}: expected a {{{{variable}}}} header "
                    f"or an indented value, got: {line!r}"
                )
            current = header.group(1)
            if current.startswith("_"):
                raise ValueError(
                    f"{path.name}:{lineno}: {{{{{current}}}}} — underscore variables "
                    "are injected by compose_prompts.py, not defined in variables.txt"
                )
            if current in parsed:
                raise ValueError(f"{path.name}:{lineno}: duplicate variable {{{{{current}}}}}")
            parsed[current] = []
        else:
            if current is None:
                raise ValueError(f"{path.name}:{lineno}: value line before any {{{{variable}}}} header")
            text = line.strip()
            weighted = WEIGHT_RE.match(text)
            if weighted:
                parsed[current].append((weighted.group(2).strip(), float(weighted.group(1))))
            else:
                parsed[current].append((text, None))
    return parsed


def split_weights(
    parsed: dict[str, list[tuple[str, float | None]]],
) -> tuple[dict[str, list[str]], dict[str, list[float]]]:
    """Split into values + normalized weights, validating the weight rules."""
    values: dict[str, list[str]] = {}
    weights: dict[str, list[float]] = {}
    for name, pairs in parsed.items():
        vals = [v for v, _ in pairs]
        ws = [w for _, w in pairs]
        if all(w is None for w in ws):
            weights[name] = [1.0 / len(vals)] * len(vals) if vals else []
        elif any(w is None for w in ws):
            raise ValueError(
                f"{{{{{name}}}}}: weights are all-or-nothing — every value needs a "
                "'<weight> ::' prefix, or none"
            )
        else:
            total = sum(ws)
            if abs(total - 1.0) > WEIGHT_TOLERANCE:
                raise ValueError(f"{{{{{name}}}}}: weights sum to {total:.6f}, expected 1.0")
            weights[name] = [float(w) for w in ws]
        values[name] = vals
    return values, weights


def template_placeholders(template: str) -> tuple[list[str], list[str]]:
    """(matrix axes, injected names), each in first-appearance order, deduped."""
    axes: list[str] = []
    injected: list[str] = []
    for name in PLACEHOLDER_RE.findall(template):
        bucket = injected if name.startswith("_") else axes
        if name not in bucket:
            bucket.append(name)
    return axes, injected


def resolve_injected(names: list[str], preamble_path: Path) -> dict[str, str]:
    """Resolve underscore placeholders to their machinery-supplied values."""
    resolved: dict[str, str] = {}
    for name in names:
        if name == "_preamble":
            resolved[name] = preamble_path.read_text(encoding="utf-8").strip()
        else:
            raise ValueError(
                f"unknown injected variable {{{{{name}}}}} — supported: {{{{_preamble}}}}"
            )
    return resolved


def largest_remainder(weights: list[float], n: int) -> list[int]:
    """Integer quotas summing to n, proportional to weights (largest remainder)."""
    exact = [w * n for w in weights]
    quotas = [math.floor(e) for e in exact]
    shortfall = n - sum(quotas)
    by_remainder = sorted(range(len(weights)), key=lambda i: exact[i] - quotas[i], reverse=True)
    for i in by_remainder[:shortfall]:
        quotas[i] += 1
    return quotas


def deck_sample(
    values: dict[str, list[str]],
    weights: dict[str, list[float]],
    axes: list[str],
    n: int,
    rng: random.Random,
) -> list[dict[str, str]]:
    """n assignments whose per-variable value counts match the weights exactly."""
    decks = []
    for name in axes:
        quotas = largest_remainder(weights[name], n)
        deck = [values[name][i] for i, q in enumerate(quotas) for _ in range(q)]
        rng.shuffle(deck)
        decks.append(deck)
    return [dict(zip(axes, row)) for row in zip(*decks)]


def fill(template: str, mapping: dict[str, str]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: mapping[m.group(1)], template)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--variables", type=Path, default=DEFAULT_VARIABLES)
    parser.add_argument(
        "--preamble", type=Path, default=DEFAULT_PREAMBLE,
        help="file injected as {{_preamble}} (default: prompts/sdf/preamble.txt)",
    )
    parser.add_argument(
        "--n-prompts", type=int, metavar="N",
        help="deck-sample exactly N prompts; per-variable shares follow the "
        "weights in variables.txt by construction. Omit for the full matrix.",
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed for --n-prompts")
    parser.add_argument("--out", type=Path, help="write composed prompts to this JSONL file")
    args = parser.parse_args()

    template = args.template.read_text(encoding="utf-8")
    values, weights = split_weights(parse_variables(args.variables))
    axes, injected_names = template_placeholders(template)

    missing = [n for n in axes if not values.get(n)]
    if missing:
        raise SystemExit(
            "template placeholders with no values in variables.txt: "
            + ", ".join(f"{{{{{n}}}}}" for n in missing)
        )
    unused = [n for n in values if n not in axes]
    if unused:
        print(
            "warning: variables defined but not in template (skipped): " + ", ".join(unused),
            file=sys.stderr,
        )
    injected = resolve_injected(injected_names, args.preamble)

    total = math.prod(len(values[n]) for n in axes)
    per_var = ", ".join(f"{n}={len(values[n])}" for n in axes)
    if args.n_prompts is not None:
        assignments = deck_sample(values, weights, axes, args.n_prompts, random.Random(args.seed))
        print(f"deck-sampled {len(assignments)} prompts (seed {args.seed}) from a {total}-combination matrix ({per_var})")
    else:
        assignments = (
            dict(zip(axes, combo)) for combo in itertools.product(*(values[n] for n in axes))
        )
        print(f"full matrix: {total} combinations ({per_var})")

    def records():
        for i, assignment in enumerate(assignments):
            prompt = fill(template, {**assignment, **injected})
            yield {"prompt_id": f"matrix_{i:06d}", "variables": assignment, "prompt": prompt}

    if args.out:
        count = 0
        with args.out.open("w", encoding="utf-8") as f:
            for rec in records():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
        print(f"wrote {count} prompts to {args.out}")
    else:
        shown = 0
        for rec in records():
            if shown < 3:
                print(f"\n--- {rec['prompt_id']} {rec['variables']} ---\n{rec['prompt']}")
                shown += 1
            else:
                print("\n(... more; use --out to write JSONL)")
                break


if __name__ == "__main__":
    main()
