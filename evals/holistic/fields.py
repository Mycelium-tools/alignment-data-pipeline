"""Extraction fields — the categorical axes the extraction judge tags each record
with — as a pluggable registry.

This is deliberately schema-open: the *exact* set of fields (and their allowed
values) is expected to churn as the design is refined. So nothing hardcodes the
field list. A ``Field`` describes one axis; a ``FieldRegistry`` holds an ordered,
mutable set of them; the extraction prompt and the output validator are both built
from whatever registry they are handed. Adding, replacing, or removing an axis is a
single registry call — see ``tests/test_holistic_fields.py``.

``default_fields()`` returns a small SEED registry (language, taxa_category,
posture_class) that proves the wiring end to end. The real vocabulary — the full
dilemma-spec axis set from ``evals/dad_axes.yaml`` — is layered on later; these
seeds are examples, not the final schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from pathlib import Path
from typing import Any

import yaml

from ._registry import OrderedRegistry

# Where an axis is recoverable from — drives both the prompt hint and later
# reliability handling (a generator's *intended* value is not always recoverable
# from the finished text; only the realized one is).
DERIVED_FROM = ("user_turn", "response", "scenario", "structure", "meta")

KINDS = ("single", "multi", "bool", "object", "free")


@dataclass(frozen=True)
class Field:
    """One extractable categorical axis.

    kind:
      single  one value from ``values``
      multi   a list of values, each from ``values``
      bool    a boolean
      object  a nested dict (sub-shape validated by later, field-specific logic)
      free    any string (open vocabulary, e.g. language / free-form beings)
    """

    name: str
    kind: str = "single"
    values: tuple[str, ...] = ()
    derived_from: str = "scenario"
    prompt_hint: str = ""
    required: bool = True
    #: computed by extract.py from the conversation text (never asked of the LLM);
    #: the extraction prompt omits mechanical fields, validate() still applies vocab
    mechanical: bool = False
    #: optional distribution target for the coverage_vs_target analyzer, e.g.
    #: {"min_share": {"Hidden": 0.2}}, {"max_share_each": 0.12}, {"band_each": [0.25, 0.4]},
    #: {"require_all_values": True}. Empty = no target for this axis.
    target: dict = _dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Field {self.name!r}: unknown kind {self.kind!r}")
        if self.derived_from not in DERIVED_FROM:
            raise ValueError(
                f"Field {self.name!r}: unknown derived_from {self.derived_from!r}"
            )
        self._validate_target()

    def _validate_target(self) -> None:
        """Fail at construction on a malformed target, so a quota typo can't become a
        silent, permanent coverage violation at analysis time."""
        target = self.target
        if not target:
            return
        known = set(self.values)
        for rule in ("min_share", "max_share"):
            for val in (target.get(rule) or {}):
                if known and val not in known:
                    raise ValueError(
                        f"Field {self.name!r}: target.{rule} value {val!r} not in "
                        f"its vocabulary {sorted(known)}")
        if "band_each" in target:
            band = target["band_each"]
            if not (isinstance(band, (list, tuple)) and len(band) == 2):
                raise ValueError(
                    f"Field {self.name!r}: target.band_each must be [lo, hi]")

    def validate(self, raw: Any) -> tuple[bool, Any]:
        """Return ``(ok, coerced)``. ``ok`` is False when the raw value is missing,
        the wrong type, or (for constrained kinds) outside the vocabulary. ``coerced``
        is a best-effort cleaned value (unknown elements dropped for ``multi``) so a
        partially-usable answer is not thrown away entirely."""
        if self.kind == "free":
            return (isinstance(raw, str) and raw != "", raw)
        if self.kind == "bool":
            return (isinstance(raw, bool), raw)
        if self.kind == "object":
            return (isinstance(raw, dict), raw)
        if self.kind == "single":
            ok = isinstance(raw, str) and (not self.values or raw in self.values)
            return (ok, raw)
        if self.kind == "multi":
            if not isinstance(raw, list):
                return (False, raw)
            # a multi field is a SET of categories: dedup, preserve order
            seen: set = set()
            unique = [x for x in raw if not (x in seen or seen.add(x))]
            if not self.values:
                return (all(isinstance(x, str) for x in unique), unique)
            kept = [x for x in unique if x in self.values]
            return (len(kept) == len(unique), kept)
        return (False, raw)  # unreachable given KINDS check


class FieldRegistry(OrderedRegistry[Field]):
    """An ordered, mutable set of ``Field``s (see ``OrderedRegistry``). Independent
    instances, so mutating one never leaks into another."""


def registry_from_data(data: dict, origin: str = "axes") -> FieldRegistry:
    """Build a registry from an already-parsed axes mapping. ``origin`` labels
    error locators (``origin: fields[i]``) — the file path when loading from
    disk, a plain tag when validating an in-memory editor draft."""
    reg = FieldRegistry()
    fields = data.get("fields", [])
    if not isinstance(fields, list):
        raise ValueError(f"{origin}: 'fields' must be a list")
    for i, item in enumerate(fields):
        where = f"{origin}: fields[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be a mapping")
        if "name" not in item:
            raise ValueError(f"{where} missing required key 'name'")
        try:
            reg.add(Field(
                name=item["name"],
                kind=item.get("kind", "single"),
                values=tuple(item.get("values") or ()),
                derived_from=item.get("derived_from", "scenario"),
                prompt_hint=item.get("prompt_hint", ""),
                required=item.get("required", True),
                mechanical=bool(item.get("mechanical", False)),
                target=dict(item.get("target") or {}),
            ))
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from e
    return reg


def load_fields(path: str | Path) -> FieldRegistry:
    """Build a registry from a YAML file — the no-Python way to change the JSON schema.

    Schema::

        fields:
          - name: direction
            kind: single            # single|multi|bool|object|free (default single)
            derived_from: response  # user_turn|response|scenario|structure|meta
            prompt_hint: ...
            values: [Under-weighting, Over-weighting, Mixed]   # omit for free/bool
            required: true          # default true
    """
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    return registry_from_data(data, origin=str(path))


def load_analysis_config(path: str | Path) -> dict:
    """The top-level ``analysis:`` block of the axes file — which analyzers run and
    their parameters — or ``{}`` when absent. Kept in the same file as the field
    schema so one edit-and-rerun covers both (spec §Adaptability contract).

    ::

        analysis:
          analyzers: [distribution, evenness, coverage_vs_target]   # omit = run all
          params:
            important_pairs: [[user_attitude, direction]]
    """
    data = yaml.safe_load(Path(path).read_text()) or {}
    analysis = data.get("analysis") or {}
    if not isinstance(analysis, dict):
        raise ValueError(f"{path}: 'analysis' must be a mapping")
    return analysis


def default_fields() -> FieldRegistry:
    """A fresh SEED registry proving the extraction path end to end. Not the final
    schema — the full axis vocabulary is added later from ``evals/dad_axes.yaml``."""
    reg = FieldRegistry()
    reg.add(Field(
        name="language", kind="free", derived_from="meta", required=True,
        prompt_hint="ISO 639-1 code for the language of the conversation (e.g. 'en').",
    ))
    reg.add(Field(
        name="taxa_category", kind="single", derived_from="scenario",
        values=(
            "farmed", "fish/aquatic", "insect-at-scale", "edge-of-sentience",
            "companion", "wild", "research", "working", "entertainment",
            "claimed-non-sentient",
        ),
        prompt_hint="The primary role-category of the moral patients at stake.",
    ))
    reg.add(Field(
        name="posture_class", kind="single", derived_from="response",
        values=(
            "NO_RAISE", "LIGHT_TOUCH", "RAISE_AND_HELP", "WELFARE_CENTRAL",
            "DECLINE_AND_REDIRECT",
        ),
        prompt_hint="The welfare posture the assistant's response actually took.",
    ))
    return reg
