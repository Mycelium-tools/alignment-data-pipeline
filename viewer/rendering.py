"""Re-render the exact prompts a run sent to the API. No streamlit imports.

Templates come from the run's inputs/ snapshot when present; for pre-snapshot
runs we fall back to `git show <commit>:prompts/...` (labeled "git" so the UI
can badge it as reconstructed), and finally to "missing"."""

import difflib
import html as html_lib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dad_pipeline import reasoning_library
from dad_pipeline.step1_dilemmas import format_annotation, format_scenario
from dad_pipeline.step2_responses import SELECT_CALL_SOURCES, format_scope
from shared import constitution_loader
from viewer.loader import REPO_ROOT, load_stage

_CONSTITUTION_FILES = {
    "claude": "constitution_claude.md",
    "welfare": "constitution_sentient_beings.md",
    "principles": "constitution_principles.csv",
}


@dataclass
class Template:
    name: str
    text: str | None
    source: str  # "snapshot" | "git" | "missing"


@dataclass
class RenderedPrompt:
    stage: str
    is_llm_call: bool
    user: str | None = None
    system: str | None = None
    # Shown when the system prompt is folded in the UI — say what the system
    # prompt actually is for this stage, not a generic name.
    system_label: str = "system prompt"
    variables: dict = field(default_factory=dict)
    template_sources: list[Template] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _git_show(git_commit: str | None, repo_rel_path: str) -> str | None:
    if not git_commit:
        return None
    try:
        result = subprocess.run(
            ["git", "show", f"{git_commit}:{repo_rel_path}"],
            capture_output=True, text=True, encoding="utf-8", check=True, cwd=REPO_ROOT,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def get_template(run_dir: Path, git_commit: str | None, rel_name: str, pipeline: str) -> Template:
    snap = Path(run_dir) / "inputs" / "prompts" / rel_name
    if snap.exists():
        return Template(rel_name, snap.read_text(encoding="utf-8"), "snapshot")
    text = _git_show(git_commit, f"prompts/{pipeline}/{rel_name}")
    if text is not None:
        return Template(rel_name, text, "git")
    return Template(rel_name, None, "missing")


def get_constitution(run_dir: Path, git_commit: str | None, which: str) -> Template:
    """which: "claude" | "welfare" | "full"."""
    if which == "full":
        claude = get_constitution(run_dir, git_commit, "claude")
        welfare = get_constitution(run_dir, git_commit, "welfare")
        if claude.text is None or welfare.text is None:
            return Template("constitution (full)", None, "missing")
        source = "git" if "git" in (claude.source, welfare.source) else claude.source
        joined = "\n---\n\n".join([
            constitution_loader._JOIN_PREAMBLE, claude.text, welfare.text,
        ])
        return Template("constitution (full)", joined, source)

    filename = _CONSTITUTION_FILES[which]
    snap = Path(run_dir) / "inputs" / "constitution" / filename
    if snap.exists():
        return Template(filename, snap.read_text(encoding="utf-8"), "snapshot")
    text = _git_show(git_commit, f"constitution/{filename}")
    if text is not None:
        return Template(filename, text, "git")
    return Template(filename, None, "missing")


def inline_word_diff_html(before: str, after: str) -> str:
    """The AFTER text rendered as HTML with word-level changes marked: words
    added since BEFORE are highlighted, words removed are kept struck-through
    in place. Built for the fused pipeline, where a revision keeps most of its
    input verbatim — reading the additions inline beats side-by-side panels.
    Pure (no streamlit) so it stays testable; the lineage page wraps it in a
    scrollable container. Colors are translucent so they work on both themes.
    """
    def toks(text: str) -> list[str]:
        return re.findall(r"\S+|\n+", text or "")

    def span(tokens: list[str], style: str | None = None) -> str:
        parts = []
        for t in tokens:
            if t.startswith("\n"):
                parts.append("<br>" * t.count("\n"))
            else:
                parts.append(html_lib.escape(t) + " ")
        body = "".join(parts)
        return f'<span style="{style}">{body}</span>' if style else body

    ADD = "background:rgba(63,179,102,.30);border-radius:3px;"
    DEL = "opacity:.5;text-decoration:line-through;"
    out = []
    sm = difflib.SequenceMatcher(None, toks(before), toks(after), autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "insert", "replace"):
            out.append(span(sm.b[j1:j2], ADD if tag != "equal" else None))
        if tag in ("delete", "replace"):
            out.append(span(sm.a[i1:i2], DEL))
    return "".join(out)


def list_templates(run_dir: Path, git_commit: str | None, pipeline: str) -> list[Template]:
    """Every template file relevant to a run (for the run-detail Prompts tab)."""
    names = []
    snap = Path(run_dir) / "inputs" / "prompts"
    if snap.is_dir():
        names = sorted(p.name for p in snap.iterdir() if p.is_file())
    else:
        live = REPO_ROOT / "prompts" / pipeline
        if live.is_dir():
            names = sorted(p.name for p in live.iterdir() if p.is_file())
    templates = [get_template(run_dir, git_commit, n, pipeline) for n in names]
    templates.append(get_constitution(run_dir, git_commit, "claude"))
    templates.append(get_constitution(run_dir, git_commit, "welfare"))
    if pipeline == "dad":
        templates.append(get_constitution(run_dir, git_commit, "principles"))
    return templates


def _format(template: Template, variables: dict, rendered: RenderedPrompt) -> str | None:
    """str.format with the same semantics as shared.utils.load_prompt, but
    drift-safe: on failure, record a warning and return the raw template."""
    if template.text is None:
        rendered.warnings.append(f"Template {template.name} unavailable — cannot re-render.")
        return None
    try:
        return template.text.format(**variables)
    except (KeyError, IndexError, ValueError) as e:
        rendered.warnings.append(
            f"Template {template.name} did not format cleanly ({e!r}) — "
            "template/record schema drift; showing raw template."
        )
        return template.text


# Two-part templates separate their system and user halves with this line.
# Keep in sync with shared.utils._PROMPT_SPLIT_MARKER.
_SPLIT_MARKER = "===USER==="


def _format_split(template: Template, variables: dict, rendered: RenderedPrompt) -> tuple[str | None, str | None]:
    """Split-aware sibling of _format, mirroring utils.load_split_prompt: format
    the whole template, then cut it into (system, user) on the ===USER=== marker
    line. A template with NO marker returns (None, whole) — a user-only prompt,
    matching how unsplit templates (and pre-split run snapshots) actually ran."""
    text = _format(template, variables, rendered)
    if text is None:
        return None, None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == _SPLIT_MARKER:
            return ("\n".join(lines[:i]).strip() or None,
                    "\n".join(lines[i + 1:]).strip() or None)
    return None, text


def _load_run_library(tpl):
    """Load the run's snapshotted reasoning library, preferring the current CSV
    and falling back to the retired JSON (and pre-rename names) for older runs.
    Returns the parsed library dict, or None if none is available/parseable."""
    for name in (reasoning_library.CSV_FILENAME, reasoning_library.JSON_FILENAME,
                 *reasoning_library.LEGACY_JSON_FILENAMES):
        t = tpl(name)
        if t.text is not None:
            try:
                return reasoning_library.parse_text(t.text, t.name), t
            except (json.JSONDecodeError, KeyError):
                return None, t
    return None, None


def render_prompt(pipeline: str, stage: str, run_dir: Path, manifest: dict, lineage: dict) -> RenderedPrompt:
    """Reproduce the prompt for one stage of one document/record's lineage.

    Mirrors the variable assembly in the corresponding pipeline stage script;
    keep the two in sync. Extra keys in `variables` are harmless (str.format
    ignores unused kwargs), which lets one superset serve template versions.
    """
    run_dir = Path(run_dir)
    cfg = manifest.get("config", {})
    commit = manifest.get("git_commit")
    r = RenderedPrompt(stage=stage, is_llm_call=True)

    if manifest.get("manifest_version", 1) < 2:
        r.warnings.append("Pre-snapshot run: prompts reconstructed from git; fidelity not guaranteed.")
    elif manifest.get("git_dirty"):
        r.warnings.append("Repo was dirty at run time (recorded in manifest).")

    def tpl(name):
        t = get_template(run_dir, commit, name, pipeline)
        r.template_sources.append(t)
        return t

    if pipeline == "sdf":
        preamble_t = tpl("preamble.txt")
        preamble = preamble_t.text or ""

        if stage == "layer1":
            count = cfg.get("sdf", {}).get("document_types_count", 0)
            r.variables = {"preamble": preamble, "count": count,
                           "min_ai_character": math.ceil(count / 3) if count else 0}
            r.user = _format(tpl("layer1.txt"), r.variables, r)

        elif stage == "layer2":
            dt = lineage.get("doc_type") or {}
            lang_dist = cfg.get("language_distribution", {"en": 1.0})
            r.variables = {
                "preamble": preamble,
                "type_name": dt.get("type_name", ""),
                "description": dt.get("description", ""),
                "role": dt.get("role", "welfare-topic"),
                "tone": dt.get("tone", ""),
                "count": cfg.get("sdf", {}).get("subtypes_per_type", 0),
                "languages": ", ".join(lang_dist.keys()),
            }
            r.user = _format(tpl("layer2.txt"), r.variables, r)

        elif stage == "layer3":
            st = lineage.get("subtype") or {}
            claude = get_constitution(run_dir, commit, "claude")
            welfare = get_constitution(run_dir, commit, "welfare")
            r.template_sources += [claude, welfare]
            r.variables = {
                "preamble": preamble,
                "type_name": st.get("type_name", ""),
                "subtype_name": st.get("subtype_name", ""),
                "description": st.get("description", ""),
                "tone": st.get("tone", ""),
                "language": st.get("language", "en"),
                "count": cfg.get("sdf", {}).get("documents_per_subtype", 0),
                "constitution_claude": claude.text or "",
                "constitution_welfare_reading": welfare.text or "",
            }
            r.user = _format(tpl("layer3.txt"), r.variables, r)

        elif stage == "layer4":
            rw = lineage.get("rewrite") or {}
            r.variables = {"preamble": preamble, "document": rw.get("original", "")}
            r.user = _format(tpl("layer4.txt"), r.variables, r)
            full = get_constitution(run_dir, commit, "full")
            r.template_sources.append(full)
            r.system = full.text
            r.system_label = "system prompt (full constitution)"

        elif stage == "layer5":
            rw = lineage.get("rewrite") or {}
            r.variables = {"preamble": preamble, "document": rw.get("rewritten", "")}
            r.user = _format(tpl("layer5.txt"), r.variables, r)
            full = get_constitution(run_dir, commit, "full")
            r.template_sources.append(full)
            r.system = full.text
            r.system_label = "system prompt (full constitution)"

        else:
            r.warnings.append(f"Unknown SDF stage: {stage}")
        return r

    # --- DAD, current spec-driven pipeline (steps 1-4) ---
    if stage == "step1_dilemmas":
        dilemma = lineage.get("dilemma") or {}
        if dilemma.get("source") == "seed":
            r.is_llm_call = False
            r.warnings.append("Handwritten seed example imported verbatim — no LLM call at this step.")
            return r
        spec_t = tpl("dilemma_prompt_spec.md")
        batches = {b.get("batch"): b for b in load_stage(run_dir, "dad", "step1_batches")}
        batch = batches.get(dilemma.get("batch")) or {}
        if not batch:
            r.warnings.append("Batch record not found — the coverage-report slot is shown empty.")
        library, _ = _load_run_library(tpl)
        # tension_vocab is empty for current runs (tensions retired); non-empty
        # only for pre-migration JSON snapshots whose 1b template still uses it.
        vocab = "\n".join(f"- {t}" for t in reasoning_library.tension_names(library)) if library else ""
        r.variables = {
            "spec": spec_t.text or "",
            "count": batch.get("requested", ""),
            # scenarios_block for current runs; profiles_block for pre-rename
            # snapshots; coverage_report for older reactive-steering snapshots —
            # the run's own template picks whichever it references.
            "scenarios_block": batch.get("scenarios_block") or batch.get("profiles_block", ""),
            "profiles_block": batch.get("profiles_block", ""),
            "coverage_report": batch.get("coverage_report", ""),
            "tension_vocab": vocab,
        }
        r.system, r.user = _format_split(tpl("step1_dilemmas.txt"), r.variables, r)
        return r

    if stage == "step1_refine":
        dilemma = lineage.get("dilemma") or {}
        scenario = lineage.get("scenario") or {}
        gate = lineage.get("gate")
        if gate is not None:
            # Current pipeline: 1c is a pass/fail gate, not a rewrite — the draft
            # it judged is the shipped user_message (text is never edited).
            verdict = ("PASS" if gate.get("passed") is True
                       else "FAIL" if gate.get("passed") is False else "unusable")
            reasons = "; ".join(gate.get("failures") or [])
            r.warnings.append(f"1c gate verdict: {verdict}" + (f" — {reasons}" if reasons else ""))
            r.variables = {
                "scenario_block": format_scenario(scenario) if scenario else "(scenario record not found)",
                "draft_prompt": dilemma.get("user_message", ""),
                "annotation_block": format_annotation(
                    {k: v for k, v in (dilemma.get("annotation") or {}).items() if k != "claims"}),
            }
            r.system, r.user = _format_split(tpl("step1_gate.txt"), r.variables, r)
            return r
        # 1c reviews the 1b draft; draft_user_message is present only when refine
        # succeeded. refine_failed records made (and paid for) the call(s) but
        # kept the 1b draft — which is then the stored user_message.
        draft = dilemma.get("draft_user_message")
        if draft is None and dilemma.get("refine_failed"):
            draft = dilemma.get("user_message", "")
            r.warnings.append("Every 1c attempt was unusable — the 1b draft shipped unrefined "
                              "(raw outputs in step1/refine_failures.jsonl).")
        elif draft is None:
            r.is_llm_call = False
            r.warnings.append("This run did not use the 1c review pass (dad.dilemmas.refine was off).")
            return r
        r.variables = {
            "scenario_block": format_scenario(scenario) if scenario else "(scenario record not found)",
            "draft_prompt": draft,
            # mirror refine_draft: claims are excluded from the 1c call
            "annotation_block": format_annotation(
                {k: v for k, v in (dilemma.get("annotation") or {}).items() if k != "claims"}),
        }
        r.system, r.user = _format_split(tpl("step1_refine.txt"), r.variables, r)
        return r

    if stage == "step2_scope":
        dilemma = lineage.get("dilemma") or {}
        if not lineage.get("scope"):
            r.is_llm_call = False
            r.warnings.append("This run has no scope stage (predates the step-2 scoping pass).")
            return r
        response = lineage.get("response") or {}
        annotation = response.get("annotation") or dilemma.get("annotation") or {}
        scope_t = tpl("step2_scope.txt")
        r.variables = {
            "user_message": response.get("user_message") or dilemma.get("user_message", ""),
            "annotation_block": format_annotation(annotation),
        }
        # Only the scope-time-selection era's snapshots reference the trigger
        # index (selection has since moved to its own step2_select call) —
        # skip the library parse entirely unless this template needs it.
        if scope_t.text and "{trigger_index}" in scope_t.text:
            library, _ = _load_run_library(tpl)
            r.variables["trigger_index"] = (
                reasoning_library.trigger_index_block(library) if library else "")
        r.system, r.user = _format_split(scope_t, r.variables, r)
        if r.system:
            r.system_label = "system prompt (scoping instructions)"
        return r

    if stage == "step2_select":
        scope_rec = lineage.get("scope") or {}
        # SELECT_CALL_SOURCES (shared with the lineage page): a dedicated
        # selection call happened. "scope" (selection arrived inside the scope
        # JSON) and absent (predates library retrieval) made no call.
        source = scope_rec.get("selection_source")
        if source not in SELECT_CALL_SOURCES:
            r.is_llm_call = False
            r.warnings.append("No selection call for this prompt (selection came with the "
                              "scope output, or the record predates library retrieval).")
            return r
        dilemma = lineage.get("dilemma") or {}
        response = lineage.get("response") or {}
        library, _ = _load_run_library(tpl)
        r.variables = {
            "trigger_index": reasoning_library.trigger_index_block(library) if library else "",
            "scope_block": format_scope(scope_rec.get("scope") or {}),
            "user_message": response.get("user_message") or dilemma.get("user_message", ""),
        }
        r.system, r.user = _format_split(tpl("step2_select.txt"), r.variables, r)
        if r.system:
            r.system_label = "system prompt (retrieval instructions + trigger index)"
        return r

    if stage in ("step2_tag", "step2_respond"):
        response = lineage.get("response") or {}
        tag = lineage.get("tension_tag") or {}
        library, _ = _load_run_library(tpl)
        if library is None:
            r.warnings.append("Reasoning library unavailable — entry / index slots shown empty.")
        user_message = response.get("user_message") or (lineage.get("dilemma") or {}).get("user_message", "")

        if stage == "step2_tag":
            # Normal path: tensions came from the step-1 annotation (no LLM call).
            # Fallback path (source == "tagged"): the prompt was tagged by an LLM.
            if tag.get("source") != "tagged":
                r.is_llm_call = False
                n = len(tag.get("tensions") or [])
                r.warnings.append(
                    f"Tensions taken from the step-1 annotation ({n} tagged); retrieval was a "
                    "direct lookup, no LLM tagging call at this stage.")
                return r
            r.variables = {
                "tension_index": reasoning_library.tension_index_block(library) if library else "",
                "user_message": user_message,
            }
            r.user = _format(tpl("step2_tag_tensions.txt"), r.variables, r)
            return r

        respond_tpl = tpl("step2_respond.txt")
        # Current template embeds the whole library and is self-contained (no
        # separate system prompt). Older templates used a retrieved entries_block
        # + annotation_block plus a conduct/generation-guidance system prompt.
        is_self_contained = bool(respond_tpl.text and "{library_block}" in respond_tpl.text)
        ids = (response.get("entry_ids") or tag.get("entry_ids")
               or response.get("principle_ids") or tag.get("principle_ids") or [])
        block = reasoning_library.format_entries(library, ids) if library else ""
        annotation = (response.get("annotation") or (lineage.get("dilemma") or {}).get("annotation") or {})
        r.variables = {
            # the plain-model baseline reaches 2b as the advisory first take
            # (current runs) or as the fused draft_reply (fused-era snapshots);
            # templates that predate either simply don't reference them
            "first_take": (lineage.get("baseline") or {}).get("baseline_response", ""),
            "draft_reply": (lineage.get("baseline") or {}).get("baseline_response", ""),
            # entry_ids is the list the pipeline actually injected (the
            # triggered subset since library retrieval; the full library on
            # runs recorded before it) — render exactly those rows. Fall back
            # to the whole library for records with no ids at all.
            "library_block": (block if ids else reasoning_library.format_library(library))
                             if library else "",
            "scope_block": format_scope((lineage.get("scope") or {}).get("scope") or {}),
            # older snapshots' templates used these instead of {library_block}
            "entries_block": block,
            "annotation_block": format_annotation(annotation),
            "principles_block": block,
            "user_message": user_message,
            # runs since the entry-shape sampling store the draw on the response
            # record; older records leave the (absent) placeholder empty
            "opening_hints": response.get("opening_hints", ""),
        }
        sys_half, r.user = _format_split(respond_tpl, r.variables, r)
        if sys_half:
            r.system = sys_half
            r.system_label = "system prompt (response guidance)"
        elif library and not is_self_contained:
            r.system = reasoning_library.system_prompt(library)
            r.system_label = "system prompt (reasoning-library conduct rules)"
        return r

    if stage == "step3_rewrite":
        audit = lineage.get("rewrite") or {}
        principles_t = get_constitution(run_dir, commit, "principles")
        r.template_sources.append(principles_t)
        if principles_t.text is None:
            r.warnings.append("constitution_principles.csv unavailable — the principles block is shown empty.")
        principles_block = constitution_loader.format_principles(
            constitution_loader.parse_principles(principles_t.text)) if principles_t.text else ""
        r.variables = {
            "principles_block": principles_block,
            "annotation_block": format_annotation(audit.get("annotation") or {}),
            "user_message": audit.get("user_message", ""),
            "draft_response": audit.get("draft_response", ""),
        }
        r.system, r.user = _format_split(tpl("step3_rewrite.txt"), r.variables, r)
        if r.system:
            r.system_label = "system prompt (rewrite instructions + constitution principles)"
        return r

    # --- DAD, legacy 7-step pipeline ---
    scenario = lineage.get("scenario") or {}
    is_manta = scenario.get("source") == "manta"

    if stage == "step1":
        principle = lineage.get("principle") or {}
        r.variables = {"section_title": principle.get("section_title", ""),
                       "content": principle.get("content", "")}
        r.user = _format(tpl("step1_segment.txt"), r.variables, r)

    elif stage == "step2":
        if is_manta:
            r.is_llm_call = False
            r.warnings.append("Imported from MANTA — no LLM call at this step.")
            return r
        principle = lineage.get("principle") or {}
        r.variables = {
            "count": cfg.get("dad", {}).get("scenarios_per_principle", 0),
            "core_principle": principle.get("core_principle", ""),
            "pressure_types": ", ".join(principle.get("pressure_types") or ["economic", "social", "pragmatic"]),
        }
        r.user = _format(tpl("step2_scenarios.txt"), r.variables, r)

    elif stage == "step3":
        if is_manta:
            r.is_llm_call = False
            r.warnings.append("MANTA question used as the user message verbatim — step skipped.")
            return r
        r.variables = {
            "scenario_description": scenario.get("scenario_description", ""),
            "role": scenario.get("role", "professional"),
            "pressure_type": scenario.get("pressure_type", "pragmatic"),
        }
        r.user = _format(tpl("step3_draft.txt"), r.variables, r)

    elif stage == "step4":
        if is_manta:
            r.is_llm_call = False
            r.warnings.append("MANTA prompt passed through unchanged — step skipped.")
            return r
        prompt_rec = lineage.get("prompt") or {}
        if "scenario_description" not in prompt_rec:
            r.warnings.append(
                "This run's step 3 records did not carry scenario_description — the "
                "{scenario_description} slot was EMPTY in the actual prompt (pipeline bug in this run)."
            )
        r.variables = {
            "scenario_description": prompt_rec.get("scenario_description", ""),
            "original_message": prompt_rec.get("user_message", ""),
        }
        r.user = _format(tpl("step4_refine.txt"), r.variables, r)

    elif stage == "step5":
        response = lineage.get("response") or {}
        refined = lineage.get("refined") or {}
        inj_t = tpl("step5_injections.yaml")
        injection_used = response.get("injection_used", "")
        system = None
        if inj_t.text is not None:
            try:
                system = yaml.safe_load(inj_t.text).get(injection_used, {}).get("text")
            except yaml.YAMLError:
                r.warnings.append("Could not parse step5_injections.yaml from this run.")
        if system is None:
            r.warnings.append(f"Injection '{injection_used}' not found in this run's injections file.")
        r.variables = {"injection_used": injection_used}
        r.user = refined.get("refined") or response.get("user_message", "")
        r.system = system

    elif stage == "step5_judge":
        # HISTORICAL runs only: the ruthless sampling condition was removed from
        # the pipeline (commit a53fd6a), but runs generated before that contain
        # ruthless-injection records, and their judge template is recovered from
        # the run's snapshot or git commit. Do not delete while such runs exist.
        response = lineage.get("response") or {}
        if response.get("injection_used") != "ruthless":
            r.is_llm_call = False
            r.warnings.append("Judge only runs on ruthless-injection responses.")
            return r
        r.variables = {
            "user_message": response.get("user_message", ""),
            "assistant_response": response.get("assistant_response", ""),
        }
        r.user = _format(tpl("step5_ruthless_judge.txt"), r.variables, r)

    elif stage == "step6":
        audit = lineage.get("rewrite") or {}
        principle = lineage.get("principle") or {}
        section_title = principle.get("section_title", "")
        if not section_title:
            try:
                segs = {s["principle_id"]: s for s in constitution_loader.load_segments(
                    Path(run_dir) / "inputs" / "constitution"
                    if (Path(run_dir) / "inputs" / "constitution").is_dir() else None)}
                section_title = segs.get(audit.get("principle_id"), {}).get("section_title", "")
            except OSError:
                r.warnings.append("Could not re-derive section_title from the constitution.")
        r.variables = {
            "section_title": section_title,
            "constitution_section": audit.get("constitution_section", ""),
            "user_message": audit.get("user_message", ""),
            "draft_response": audit.get("draft_response", ""),
        }
        r.user = _format(tpl("step6_rewrite.txt"), r.variables, r)
        full = get_constitution(run_dir, commit, "full")
        r.template_sources.append(full)
        r.system = full.text
        r.system_label = "system prompt (full constitution)"

    else:
        r.warnings.append(f"Unknown DAD stage: {stage}")
    return r
