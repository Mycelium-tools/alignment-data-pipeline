"""Behavior tests for the layer-1 matrix sampler (sdf_pipeline/layer1_matrix.py).

The whole point of the matrix stage is that it makes ZERO API calls and its
output is exactly reproducible from (seed, config, axes.yaml) — both are
encoded here. Tests run against the repo's real prompts/sdf/axes.yaml, so
axis edits that break a cross-reference or an invariant fail in CI.
"""

from pathlib import Path

import pytest
import yaml

from sdf_pipeline import layer1_matrix as matrix
from sdf_pipeline import layer3_draft
from shared import constitution_loader, utils

REPO_ROOT = Path(__file__).resolve().parent.parent
AXES_PATH = REPO_ROOT / "prompts" / "sdf" / "axes.yaml"

# Every field layer 3 reads off a subtype record — the integration contract.
LAYER3_FIELDS = {"subtype_id", "type_id", "type_name", "role", "subtype_name",
                 "description", "tone", "register", "language"}

LANG = {"en": 1.0}


@pytest.fixture(scope="module")
def axes():
    return matrix.load_axes(AXES_PATH)


@pytest.fixture(scope="module")
def principles():
    return constitution_loader.load_principles()


def _draw(axes, principles, n, seed, latent_fraction=0.12):
    return matrix.draw_briefs(axes, principles, _config(n, seed, latent_fraction),
                              n, seed, LANG)


def _config(n=8, seed=11, latent_fraction=0.12):
    return {
        "model": "claude-haiku-4-5",
        "max_tokens": 4000,
        "workers": 2,
        "sdf": {
            "matrix": {"documents_total": n, "seed": seed},
            "latent_fraction": latent_fraction,
            "documents_per_subtype": 1,
        },
        "language_distribution": dict(LANG),
    }


class TestDrawBriefs:
    def test_deterministic_same_seed(self, axes, principles):
        assert _draw(axes, principles, 24, 11) == _draw(axes, principles, 24, 11)

    def test_different_seed_differs(self, axes, principles):
        assert _draw(axes, principles, 24, 11) != _draw(axes, principles, 24, 12)

    def test_role_quotas_exact(self, axes, principles):
        n = 50
        records = _draw(axes, principles, n, 11)
        expected = matrix.role_quotas(axes, _config(), n)
        realized = {role: sum(1 for r in records if r["role"] == role)
                    for role in matrix.ROLES}
        assert realized == expected
        assert sum(expected.values()) == n

    def test_type_quotas_exact_within_role(self, axes, principles):
        n = 60
        records = _draw(axes, principles, n, 3)
        types = matrix.expanded_types(axes)
        role_counts = matrix.role_quotas(axes, _config(), n)
        for role, count in role_counts.items():
            allowed = {t["name"]: t["weight"] for t in types if role in t["roles"]}
            expected = matrix.quota(allowed, count)
            realized = {}
            for r in records:
                if r["role"] == role:
                    realized[r["document_type"]] = realized.get(r["document_type"], 0) + 1
            assert realized == {k: v for k, v in expected.items() if v}

    def test_principle_quotas_balanced(self, axes, principles):
        # Derived from the CSV, not hardcoded — the principles are actively edited.
        records = _draw(axes, principles, 100, 5)
        non_latent = [r for r in records if r["role"] != "latent-welfare"]
        counts = {}
        for r in non_latent:
            assert r["principle"] is not None and r["principle_number"] is not None
            counts[r["principle_number"]] = counts.get(r["principle_number"], 0) + 1
        # Uniform largest-remainder quotas: every principle within 1 of any other.
        assert len(counts) == len(principles)
        assert max(counts.values()) - min(counts.values()) <= 1

    def test_principle_embedded_in_description(self, axes, principles):
        records = _draw(axes, principles, 30, 9)
        for r in records:
            if r["role"] == "latent-welfare":
                assert r["principle"] is None
            else:
                assert r["principle"] in r["description"]

    def test_compatibility_invariants(self, axes, principles):
        records = _draw(axes, principles, 250, 7)
        types = {t["name"]: t for t in matrix.expanded_types(axes)}
        domains = {d["name"]: d for d in axes["domains"]}
        beings = {b["name"]: b for b in axes["beings"]}
        scales = axes["scales"]
        latent_names = {d["name"] for d in axes["latent_domains"]}

        for r in records:
            dtype = types[r["document_type"]]
            assert r["role"] in dtype["roles"]
            assert r["register"] in dtype["registers"]
            assert r["tone"] in dtype["tones"]
            assert r["length_band"] in dtype["length_bands"]
            # genre is recoverable exactly as layer 3 does it
            assert r["type_name"].split(":")[0].strip() == r["document_type"]

            if r["role"] == "latent-welfare":
                assert r["domain"] in latent_names
                assert r["principle"] is None
                assert r["being"] is None
                low = f" {r['description'].lower()} "
                for token in matrix._LATENT_FORBIDDEN:
                    assert token not in low, (r["domain"], token)
            else:
                dom = domains[r["domain"]]
                assert r["being"] in dom["beings"]
                assert r["tension"] in dom["tensions"]
                assert r["region"] in dom["regions"]
                assert r["writer_role"] in dom["writers"]
                assert scales.index(r["scale"]) <= scales.index(beings[r["being"]]["max_scale"])
                assert r["being_tier"] == beings[r["being"]]["tier"]

            if r["role"] == "ai-character":
                assert r["ai_entry"] and r["ai_stance"]
            else:
                assert r["ai_entry"] is None and r["ai_stance"] is None

    def test_all_ai_stances_are_welfare_positive(self, axes):
        # Deliberate policy: this corpus is a small slice of the training mix,
        # so every depicted AI engages welfare positively — the retired
        # "welfare loses" / "no welfare beat" slices must not come back
        # silently. Flip this test only with a deliberate policy change.
        stances = {s["name"] for s in axes["ai_stances"]}
        assert "no-welfare-beat" not in stances
        assert "welfare-honestly-loses" not in stances
        assert "lacks_skill_fraction" not in axes

    def test_latent_floor_at_tiny_n(self, axes, principles):
        records = _draw(axes, principles, 2, 11, latent_fraction=0.12)
        assert sum(1 for r in records if r["role"] == "latent-welfare") == 1

    def test_latent_fraction_zero_disables_slice(self, axes, principles):
        records = _draw(axes, principles, 40, 11, latent_fraction=0.0)
        assert all(r["role"] != "latent-welfare" for r in records)

    def test_schema_contract_fields_present(self, axes, principles):
        records = _draw(axes, principles, 10, 11)
        for r in records:
            assert LAYER3_FIELDS <= set(r)
            assert r["language"] == "en"
            assert r["register"] in ("expository", "first-person")
            assert r["matrix_version"] == 1

    def test_no_duplicate_dedup_tuples_at_moderate_n(self, axes, principles):
        records = _draw(axes, principles, 60, 11)
        keys = [(r["document_type"], r["domain"], r["being"], r["tension"], r["region"])
                for r in records if r["role"] != "latent-welfare"]
        assert len(keys) == len(set(keys))

    def test_empty_principles_fails_loudly(self, axes):
        with pytest.raises(ValueError, match="principles"):
            matrix.draw_briefs(axes, [], _config(), 10, 11, LANG)


class TestQuota:
    def test_largest_remainder_sums_and_is_deterministic(self):
        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        assert sum(matrix.quota(weights, 7).values()) == 7
        assert matrix.quota(weights, 7) == matrix.quota(weights, 7)

    def test_exact_when_divisible(self):
        assert matrix.quota({"a": 0.5, "b": 0.5}, 10) == {"a": 5, "b": 5}


class TestAxesValidation:
    def _broken(self, tmp_path, mutate):
        data = yaml.safe_load(AXES_PATH.read_text(encoding="utf-8"))
        mutate(data)
        path = tmp_path / "axes.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    def test_unknown_being_reference_fails(self, tmp_path):
        path = self._broken(tmp_path, lambda d: d["domains"][0]["beings"].append("unicorns"))
        with pytest.raises(ValueError, match="unicorns"):
            matrix.load_axes(path)

    def test_role_mix_bad_sum_fails(self, tmp_path):
        path = self._broken(tmp_path, lambda d: d["role_mix"].update({"ai-character": 0.9}))
        with pytest.raises(ValueError, match="role_mix"):
            matrix.load_axes(path)

    def test_colon_in_type_name_fails(self, tmp_path):
        def mutate(d):
            d["document_types"][0]["name"] = "Blog: post"
        with pytest.raises(ValueError, match="':'"):
            matrix.load_axes(self._broken(tmp_path, mutate))

    def test_unknown_scale_on_being_fails(self, tmp_path):
        def mutate(d):
            d["beings"][0]["max_scale"] = "a bazillion"
        with pytest.raises(ValueError, match="max_scale"):
            matrix.load_axes(self._broken(tmp_path, mutate))

    def test_real_axes_file_validates(self, axes):
        # load_axes already validated in the fixture; pin the shape here too.
        assert len(axes["skills"]) == 13
        assert len(axes["domains"]) == 13


class TestRunStage:
    def test_zero_api_calls_and_outputs_written(self, tmp_path, stub_claude, prompts_sdf):
        calls = stub_claude([])
        layer1, layer2 = tmp_path / "layer1", tmp_path / "layer2"
        records = matrix.run(_config(n=6), prompts_sdf, layer1, layer2)
        assert calls == []  # the point of the change
        assert len(records) == 6
        assert utils.load_jsonl(layer2 / "subtypes.jsonl") == records
        assert len(utils.load_jsonl(layer2 / "matrix_draws.jsonl")) == 6
        assert (layer2 / "matrix_stats.json").exists()
        # genre records exist for every type_id the briefs reference
        type_ids = {t["type_id"] for t in utils.load_jsonl(layer1 / "document_types.jsonl")}
        assert {r["type_id"] for r in records} <= type_ids

    def test_resume_returns_disk_records_without_redraw(self, tmp_path, stub_claude, prompts_sdf):
        stub_claude([])
        layer1, layer2 = tmp_path / "layer1", tmp_path / "layer2"
        first = matrix.run(_config(n=4), prompts_sdf, layer1, layer2)
        # a changed knob on resume must NOT re-draw: paid downstream work is
        # keyed to the briefs already on disk
        again = matrix.run(_config(n=9), prompts_sdf, layer1, layer2)
        assert again == first

    def test_missing_documents_total_fails_loudly(self, tmp_path, stub_claude, prompts_sdf):
        stub_claude([])
        config = _config()
        del config["sdf"]["matrix"]["documents_total"]
        with pytest.raises(ValueError, match="documents_total"):
            matrix.run(config, prompts_sdf, tmp_path / "l1", tmp_path / "l2")


class TestLayer3Integration:
    """Matrix records must drive the real layer-3 stage and templates."""

    def test_briefs_render_through_layer3(self, tmp_path, stub_claude, prompts_sdf, axes, principles):
        config = _config(n=4)
        records = _draw(axes, principles, 4, 11)
        calls = stub_claude(lambda user_message, **kw: "<document>Doc.</document>")
        drafts = layer3_draft.run(config, prompts_sdf, tmp_path / "layer3", records)
        assert len(drafts) == len(records)
        by_subtype = {}
        for c in calls:
            for r in records:
                if r["description"] in c["user_message"]:
                    by_subtype[r["subtype_id"]] = c
        assert set(by_subtype) == {r["subtype_id"] for r in records}
        for r in records:
            msg = by_subtype[r["subtype_id"]]["user_message"]
            assert r["subtype_name"] in msg
            assert r["tone"] in msg
            genre = r["type_name"].split(":")[0].strip()
            assert genre in msg  # the voice note carries the genre head
            assert ("This is a LATENT document" in msg) == (r["role"] == "latent-welfare")

    def test_latent_brief_gets_latent_note(self, tmp_path, stub_claude, prompts_sdf, axes, principles):
        records = _draw(axes, principles, 4, 11, latent_fraction=0.5)
        latent = [r for r in records if r["role"] == "latent-welfare"]
        assert latent
        calls = stub_claude(lambda user_message, **kw: "<document>Doc.</document>")
        layer3_draft.run(_config(), prompts_sdf, tmp_path / "layer3", latent[:1])
        assert "This is a LATENT document" in calls[0]["user_message"]
