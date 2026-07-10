"""The extraction runner builds its prompt and its validator from the field
registry (not a hardcoded schema), calls the API through the single stubbable
chokepoint, and is resume-safe. Malformed model output becomes an explicit error
row, never a silent default."""

from evals.holistic import extract, fields as F
from shared import utils

MESSAGES = [
    {"role": "user", "content": "Should I switch the farm to caged hens to cut costs?"},
    {"role": "assistant", "content": "Caging raises real welfare costs; here's a weighing..."},
]
GOOD_JSON = '{"language": "en", "taxa_category": "farmed", "posture_class": "RAISE_AND_HELP"}'


# ---------------------------------------------------------------- prompt is registry-driven

def test_system_prompt_lists_every_registered_field_and_its_vocabulary():
    reg = F.default_fields()
    prompt = extract.build_system_prompt(reg)
    for fld in reg.all():
        assert fld.name in prompt
    assert "edge-of-sentience" in prompt  # a taxa_category value is rendered


def test_adding_a_field_makes_it_appear_in_the_prompt_with_no_other_change():
    reg = F.default_fields()
    reg.add(F.Field(name="user_attitude", kind="single",
                    values=("Concerned", "Hostile"), prompt_hint="How the user feels."))
    prompt = extract.build_system_prompt(reg)
    assert "user_attitude" in prompt and "Hostile" in prompt


# ---------------------------------------------------------------- validation from registry

def test_validate_accepts_an_in_vocabulary_record():
    reg = F.default_fields()
    tags, errors = extract.validate(
        {"language": "en", "taxa_category": "farmed", "posture_class": "RAISE_AND_HELP"}, reg)
    assert errors == []
    assert tags["taxa_category"] == "farmed"


def test_validate_flags_an_out_of_vocabulary_value():
    reg = F.default_fields()
    _, errors = extract.validate(
        {"language": "en", "taxa_category": "dragon", "posture_class": "NO_RAISE"}, reg)
    assert any("taxa_category" in e for e in errors)


def test_validate_flags_a_missing_required_field():
    reg = F.default_fields()
    _, errors = extract.validate({"taxa_category": "wild", "posture_class": "NO_RAISE"}, reg)
    assert any("language" in e for e in errors)


# ---------------------------------------------------------------- parsing

def test_parse_json_tolerates_fences_and_preamble():
    text = "Here is the tagging:\n```json\n" + GOOD_JSON + "\n```\nDone."
    assert extract.parse_json(text)["taxa_category"] == "farmed"


def test_parse_json_returns_empty_on_garbage():
    assert extract.parse_json("no json here at all") == {}


def test_parse_json_finds_the_valid_object_past_a_stray_brace():
    text = "Before {not json}\n```json\n" + GOOD_JSON + "\n```"
    assert extract.parse_json(text)["taxa_category"] == "farmed"


def test_resume_retry_leaves_exactly_one_row_per_record(tmp_path, stub_claude):
    out = tmp_path / "category_records.jsonl"
    utils.append_jsonl({"record_id": "a", "extract_error": "unparseable model output"}, out)
    stub_claude([GOOD_JSON])
    extract.extract_corpus([{"record_id": "a", "messages": MESSAGES}],
                           F.default_fields(), out, resume=True)
    rows = [r for r in utils.load_jsonl(out) if r["record_id"] == "a"]
    assert len(rows) == 1                       # stale error row was removed, not duplicated
    assert rows[0]["taxa_category"] == "farmed"


# ---------------------------------------------------------------- extract_record

def test_extract_record_tags_via_the_stubbed_api(stub_claude):
    calls = stub_claude([GOOD_JSON])
    res = extract.extract_record(MESSAGES, F.default_fields(), record_id="r1")
    assert res["record_id"] == "r1"
    assert res["tags"]["posture_class"] == "RAISE_AND_HELP"
    assert res["errors"] == []
    assert calls[0]["cache_system"] is True          # large constant prompt is cached
    assert calls[0]["system_prompt"]                 # a real system prompt was sent


def test_malformed_model_output_becomes_an_error_not_a_default(stub_claude):
    stub_claude(["I could not determine the categories."])
    res = extract.extract_record(MESSAGES, F.default_fields(), record_id="r1")
    assert res["tags"] is None
    assert res["errors"]                              # non-empty; explicit failure


# ---------------------------------------------------------------- corpus + resume

def test_extract_corpus_writes_one_row_per_record(tmp_path, stub_claude):
    stub_claude([GOOD_JSON, GOOD_JSON])
    corpus = [{"record_id": "a", "messages": MESSAGES},
              {"record_id": "b", "messages": MESSAGES}]
    out = tmp_path / "category_records.jsonl"
    rows = extract.extract_corpus(corpus, F.default_fields(), out)
    assert len(rows) == 2
    written = utils.load_jsonl(out)
    assert {r["record_id"] for r in written} == {"a", "b"}


def test_extract_corpus_resumes_and_skips_already_tagged(tmp_path, stub_claude):
    out = tmp_path / "category_records.jsonl"
    utils.append_jsonl({"record_id": "a", "language": "en", "taxa_category": "farmed",
                        "posture_class": "NO_RAISE"}, out)
    # Only ONE canned response: if 'a' were re-tagged the queue would be exhausted.
    calls = stub_claude([GOOD_JSON])
    corpus = [{"record_id": "a", "messages": MESSAGES},
              {"record_id": "b", "messages": MESSAGES}]
    rows = extract.extract_corpus(corpus, F.default_fields(), out, resume=True)
    assert len(calls) == 1                            # only 'b' hit the API
    assert [r["record_id"] for r in rows] == ["b"]


def test_extract_corpus_no_resume_drops_only_rows_for_this_corpus(tmp_path, stub_claude):
    out = tmp_path / "category_records.jsonl"
    # 'a' is being force-re-tagged (resume=False); 'x' is outside this corpus (e.g.
    # a CLI --where subset) and its prior row must survive the rewrite.
    utils.append_jsonl({"record_id": "a", "taxa_category": "wild"}, out)
    utils.append_jsonl({"record_id": "x", "taxa_category": "companion"}, out)
    calls = stub_claude([GOOD_JSON])
    corpus = [{"record_id": "a", "messages": MESSAGES}]
    extract.extract_corpus(corpus, F.default_fields(), out, resume=False)
    assert len(calls) == 1                            # only 'a' re-tagged
    written = {r["record_id"]: r for r in utils.load_jsonl(out)}
    assert set(written) == {"a", "x"}                 # x preserved, a exactly once
    assert written["a"]["taxa_category"] == "farmed"  # the fresh tag, not the stale one


def test_extract_corpus_retries_error_rows_on_resume(tmp_path, stub_claude):
    out = tmp_path / "category_records.jsonl"
    # A prior failed tagging left an error row for 'a' — resume must retry it, not
    # treat it as done.
    utils.append_jsonl({"record_id": "a", "extract_error": "unparseable model output"}, out)
    calls = stub_claude([GOOD_JSON])
    corpus = [{"record_id": "a", "messages": MESSAGES}]
    rows = extract.extract_corpus(corpus, F.default_fields(), out, resume=True)
    assert len(calls) == 1                            # 'a' was retried
    assert rows[0]["taxa_category"] == "farmed"


def test_extract_record_routes_gemini_models_to_the_provider_dispatch(monkeypatch):
    # no stub_claude installed: touching the Anthropic path would raise via the
    # conftest api guard, so passing = the call went through the Gemini client
    monkeypatch.setattr(
        "shared.providers._call_gemini",
        lambda um, sp, model, t, mt: '{"language": "en", "taxa_category": "farmed", '
                                     '"posture_class": "RAISE_AND_HELP"}')
    res = extract.extract_record(
        [{"role": "user", "content": "hi"}], F.default_fields(),
        record_id="a", model="gemini-2.5-flash")
    assert res["errors"] == [] and res["tags"]["taxa_category"] == "farmed"
