"""Tests for sdf_pipeline/compose_prompts.py (offline, no API)."""

import json
import random
import sys
from collections import Counter

import pytest

from sdf_pipeline import compose_prompts as cp


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# --- variables.txt parsing ---

def test_parse_plain_and_weighted_values(tmp_path):
    path = write(tmp_path / "variables.txt", (
        "# comment\n"
        "{{tone}}  # description\n"
        "    0.5 :: neutral\n"
        "    0.5 :: skeptical, with :: in the prose\n"
        "\n"
        "{{culture}}\n"
        "    # --- section divider ---\n"
        "    France\n"
        "    the United States\n"
    ))
    parsed = cp.parse_variables(path)
    assert parsed["tone"] == [("neutral", 0.5), ("skeptical, with :: in the prose", 0.5)]
    assert parsed["culture"] == [("France", None), ("the United States", None)]


def test_split_weights_uniform_fallback():
    values, weights = cp.split_weights({"a": [("x", None), ("y", None)]})
    assert values["a"] == ["x", "y"]
    assert weights["a"] == [0.5, 0.5]


def test_split_weights_rejects_mixed():
    with pytest.raises(ValueError, match="all-or-nothing"):
        cp.split_weights({"a": [("x", 0.5), ("y", None)]})


def test_split_weights_rejects_bad_sum():
    with pytest.raises(ValueError, match="sum"):
        cp.split_weights({"a": [("x", 0.5), ("y", 0.4)]})


def test_parse_rejects_underscore_definition(tmp_path):
    path = write(tmp_path / "variables.txt", "{{_preamble}}\n    text\n")
    with pytest.raises(ValueError, match="injected"):
        cp.parse_variables(path)


def test_parse_rejects_duplicate_variable(tmp_path):
    path = write(tmp_path / "variables.txt", "{{a}}\n    x\n{{a}}\n    y\n")
    with pytest.raises(ValueError, match="duplicate"):
        cp.parse_variables(path)


def test_parse_rejects_value_before_header(tmp_path):
    path = write(tmp_path / "variables.txt", "    orphan value\n")
    with pytest.raises(ValueError, match="before any"):
        cp.parse_variables(path)


# --- quota arithmetic and deck sampling ---

def test_largest_remainder_quotas():
    assert cp.largest_remainder([0.5, 0.3, 0.2], 7) == [4, 2, 1]
    assert cp.largest_remainder([0.5, 0.5], 5) == [3, 2]
    assert sum(cp.largest_remainder([0.11, 0.29, 0.6], 100)) == 100


def test_deck_sample_exact_marginals():
    values = {"a": ["a1", "a2"], "b": ["b1", "b2", "b3"]}
    weights = {"a": [0.7, 0.3], "b": [1 / 3] * 3}
    rows = cp.deck_sample(values, weights, ["a", "b"], 10, random.Random(0))
    assert len(rows) == 10
    assert Counter(r["a"] for r in rows) == {"a1": 7, "a2": 3}
    assert Counter(r["b"] for r in rows) == {"b1": 4, "b2": 3, "b3": 3}


def test_deck_sample_is_seed_deterministic():
    values = {"a": [str(i) for i in range(5)]}
    weights = {"a": [0.2] * 5}
    one = cp.deck_sample(values, weights, ["a"], 20, random.Random(7))
    two = cp.deck_sample(values, weights, ["a"], 20, random.Random(7))
    assert one == two


# --- template handling ---

def test_template_placeholders_split_and_dedupe():
    axes, injected = cp.template_placeholders("{{_preamble}} {{a}} {{b}} {{a}}")
    assert axes == ["a", "b"]
    assert injected == ["_preamble"]


def test_fill_replaces_every_slot():
    out = cp.fill("{{_p}}: {{a}} and {{a}}", {"_p": "P", "a": "x"})
    assert out == "P: x and x"


def test_resolve_injected_preamble(tmp_path):
    preamble = write(tmp_path / "preamble.txt", "The preamble.\n")
    assert cp.resolve_injected(["_preamble"], preamble) == {"_preamble": "The preamble."}


def test_resolve_injected_rejects_unknown(tmp_path):
    with pytest.raises(ValueError, match="_destination"):
        cp.resolve_injected(["_destination"], tmp_path / "preamble.txt")


# --- CLI end-to-end ---

def test_cli_deck_sample_writes_jsonl(tmp_path, monkeypatch, capsys):
    template = write(tmp_path / "template.txt", "{{_preamble}}\n\nType: {{doc}}\nTone: {{tone}}\n")
    variables = write(tmp_path / "variables.txt", (
        "{{doc}}\n"
        "    0.75 :: article\n"
        "    0.25 :: memo\n"
        "{{tone}}\n"
        "    neutral\n"
        "    skeptical\n"
    ))
    preamble = write(tmp_path / "preamble.txt", "PREAMBLE TEXT\n")
    out = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "compose_prompts.py", "--template", str(template), "--variables", str(variables),
        "--preamble", str(preamble), "--n-prompts", "8", "--seed", "0", "--out", str(out),
    ])
    cp.main()

    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 8
    assert Counter(r["variables"]["doc"] for r in records) == {"article": 6, "memo": 2}
    assert Counter(r["variables"]["tone"] for r in records) == {"neutral": 4, "skeptical": 4}
    for rec in records:
        assert set(rec["variables"]) == {"doc", "tone"}  # injected slots stay out
        assert rec["prompt"].startswith("PREAMBLE TEXT\n")
        assert "{{" not in rec["prompt"]


def test_cli_full_matrix_without_n(tmp_path, monkeypatch, capsys):
    template = write(tmp_path / "template.txt", "A: {{a}} B: {{b}}\n")
    variables = write(tmp_path / "variables.txt", "{{a}}\n    1\n    2\n{{b}}\n    x\n    y\n    z\n")
    out = tmp_path / "all.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "compose_prompts.py", "--template", str(template), "--variables", str(variables),
        "--out", str(out),
    ])
    cp.main()
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 6
    assert len({r["prompt"] for r in records}) == 6


def test_cli_errors_on_missing_values(tmp_path, monkeypatch):
    template = write(tmp_path / "template.txt", "{{a}} {{ghost}}\n")
    variables = write(tmp_path / "variables.txt", "{{a}}\n    1\n")
    monkeypatch.setattr(sys, "argv", [
        "compose_prompts.py", "--template", str(template), "--variables", str(variables),
    ])
    with pytest.raises(SystemExit, match="ghost"):
        cp.main()
