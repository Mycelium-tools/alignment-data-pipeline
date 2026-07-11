"""Compose layer-3 input prompts from a template and a variables file.

EXPERIMENTAL replacement for SDF layers 1-2: instead of two LLM calls
generating document types and subtypes, a combinatorial matrix of pre-written
variables is expanded deterministically into thousands of unique prompts.

Inputs
------
- Template (``prompts/sdf/matrix/template.txt``): plain text with
  ``{{variable_name}}`` slots. NOT loaded through ``shared.utils.load_prompt``
  (no ``str.format``), so literal braces are harmless.
- Variables (``prompts/sdf/matrix/variables.txt``)::

      {{varname}}  # optional description
          value 1
          value 2

  Full-line ``#`` comments and blank lines are ignored anywhere.

The composer takes the cartesian product of every variable that appears in
the template. Variables defined but unused are skipped with a warning;
placeholders with no defined values are an error.

Usage
-----
    # Dry run: print combination count and a few sample prompts
    python sdf_pipeline/compose_prompts.py

    # Write all composed prompts to JSONL
    python sdf_pipeline/compose_prompts.py --out composed_prompts.jsonl

    # Random sample of the matrix (seeded)
    python sdf_pipeline/compose_prompts.py --sample 50 --seed 0 --out sample.jsonl

Output records: ``{"prompt_id": ..., "variables": {...}, "prompt": ...}``.

A later stage may add a lightweight LLM filter for illogical combinations
before the prompts ship to layer 3; this script stays offline and free.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / "prompts" / "sdf" / "matrix" / "template.txt"
DEFAULT_VARIABLES = REPO_ROOT / "prompts" / "sdf" / "matrix" / "variables.txt"

PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
VAR_HEADER_RE = re.compile(r"^\{\{([A-Za-z0-9_]+)\}\}\s*(?:#\s*(.*))?$")


def parse_variables(path: Path) -> dict[str, list[str]]:
    """Parse a variables.txt file into {name: [values]}."""
    variables: dict[str, list[str]] = {}
    current: str | None = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        header = VAR_HEADER_RE.match(line.strip())
        if header and not line.startswith((" ", "\t")):
            current = header.group(1)
            if current in variables:
                raise ValueError(f"{path.name}:{lineno}: duplicate variable {{{{{current}}}}}")
            variables[current] = []
        elif line.startswith((" ", "\t")):
            if current is None:
                raise ValueError(f"{path.name}:{lineno}: value line before any {{{{variable}}}} header")
            variables[current].append(line.strip())
        else:
            raise ValueError(
                f"{path.name}:{lineno}: expected a {{{{variable}}}} header or an indented value, got: {line!r}"
            )
    return variables


def template_placeholders(template: str) -> list[str]:
    """Placeholder names in first-appearance order, deduplicated."""
    seen: list[str] = []
    for name in PLACEHOLDER_RE.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def compose(template: str, variables: dict[str, list[str]]) -> list[dict]:
    """Fill the template with every combination of the variables it uses."""
    names = template_placeholders(template)
    missing = [n for n in names if not variables.get(n)]
    if missing:
        raise ValueError(
            "template placeholders with no values in variables.txt: "
            + ", ".join(f"{{{{{n}}}}}" for n in missing)
        )
    unused = [n for n in variables if n not in names]
    if unused:
        print(
            "warning: variables defined but not in template (skipped): " + ", ".join(unused),
            file=sys.stderr,
        )

    records = []
    for i, combo in enumerate(itertools.product(*(variables[n] for n in names))):
        assignment = dict(zip(names, combo))
        prompt = PLACEHOLDER_RE.sub(lambda m: assignment[m.group(1)], template)
        records.append({"prompt_id": f"matrix_{i:06d}", "variables": assignment, "prompt": prompt})
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--variables", type=Path, default=DEFAULT_VARIABLES)
    parser.add_argument("--out", type=Path, help="write composed prompts to this JSONL file")
    parser.add_argument("--sample", type=int, help="randomly sample N combinations instead of all")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed for --sample")
    args = parser.parse_args()

    template = args.template.read_text(encoding="utf-8")
    variables = parse_variables(args.variables)
    records = compose(template, variables)
    total = len(records)

    if args.sample is not None and args.sample < total:
        records = random.Random(args.seed).sample(records, args.sample)

    per_var = ", ".join(f"{n}={len(variables[n])}" for n in template_placeholders(template))
    print(f"{total} combinations ({per_var})" + (f"; sampled {len(records)}" if len(records) < total else ""))

    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"wrote {len(records)} prompts to {args.out}")
    else:
        for rec in records[:3]:
            print(f"\n--- {rec['prompt_id']} {rec['variables']} ---\n{rec['prompt']}")
        if len(records) > 3:
            print(f"\n(... {len(records) - 3} more; use --out to write JSONL)")


if __name__ == "__main__":
    main()
