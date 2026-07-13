"""Edit axes page: form-based editing of evals/dad_axes.yaml — the diversity
categories the holistic judge tags every DAD conversation with. All logic lives
in evals/holistic/axes_io.py (ruamel round-trip, validation, cost classification,
coupling warnings); this file only renders a session-state draft document."""

import sys
import zlib
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.holistic import axes_io
from evals.holistic import extract as extract_mod
from evals.holistic import fields as fields_mod
from evals.holistic import synthesize as synthesize_mod
from evals.holistic_dad import DEFAULT_EXTRACT_PROMPT, DEFAULT_SYNTH_PROMPT

st.title("Edit axes")
st.caption("These are the **diversity categories** the holistic judge tags every "
           "DAD conversation with (`evals/dad_axes.yaml`). Edit them here — the "
           "judge's extraction prompt is rendered from this file, so changes take "
           "effect automatically on the next **Tag** in *Run diversity*. The "
           "mechanistic `analysis:` block (which report metrics run) is edited in "
           "*Raw YAML* below.")

with st.expander(":material/school: How this works — the whole diversity loop"):
    st.markdown(
        "1. **This file** (`evals/dad_axes.yaml`) lists the categories (axes) — "
        "each with its allowed values and a one-line hint.\n"
        "2. **Tag** (on *Run diversity*) sends every final conversation to a cheap "
        "LLM judge. The judge's prompt is built automatically from these axes plus "
        "the *extraction prompt* below — so editing either changes what it outputs. "
        "Each conversation gets one JSON of tags.\n"
        "3. Tags land in a **bundle** keyed by the exact axes + model + extraction "
        "prompt. Unchanged inputs resume the same bundle (already-tagged records are "
        "skipped — free); changing any of them starts a fresh bundle (**paid** — one "
        "call per record). Old bundles are never overwritten, so variants sit "
        "side-by-side.\n"
        "4. **Analyze** runs the mechanistic analyzers over the tags — distribution, "
        "evenness, coverage vs the `target:` quotas, correlations, drift — plus one "
        "LLM synthesis call, and writes the report you browse on *Run diversity*. "
        "Quota and `analysis:` edits only affect this step, so they are **free**.\n"
        "5. The same tags power the facet filters in *Judge → Score a run*.")


def _draft():
    if "axes_draft" not in st.session_state:
        loaded = axes_io.load_doc(axes_io.AXES_PATH)
        if not axes_io.structurally_editable(loaded):
            st.error(f"`{axes_io.AXES_PATH}` is not editable here — it must be a "
                     "YAML mapping with a non-empty `fields:` list of mappings, "
                     "each with a string `name`. Fix the file on disk first.")
            st.stop()
        st.session_state.axes_draft = loaded
    return st.session_state.axes_draft


doc = _draft()
rev = st.session_state.get("axes_rev", 0)
disk_doc = axes_io.load_doc(axes_io.AXES_PATH)
names = axes_io.field_names(doc)

left, right = st.columns([1, 2.2], gap="large")

with left:
    if st.button(":material/add: Add axis", type="primary"):
        base, n = "new_axis", 1
        name = base
        while name in names:
            n += 1
            name = f"{base}_{n}"
        axes_io.add_field(doc, name)
        st.session_state.axes_sel = name
        st.rerun()
    sel = st.session_state.get("axes_sel")
    sel = sel if sel in names else (names[0] if names else None)
    for i, name in enumerate(names):
        entry = axes_io.field_entry(doc, name)
        quota = " ·  🔵" if entry.get("target") else ""
        label = f"{'▸ ' if name != sel else '▾ '}`{name}`  ·  " \
                f"{entry.get('kind', 'single')}{quota}"
        if st.button(label, key=f"axrow_{i}"):
            st.session_state.axes_sel = name
            st.rerun()
    st.caption("One row per category. 🔵 = has a coverage quota. Click a row to "
               "edit it on the right.")

with right:
    if sel is not None:
        entry = axes_io.field_entry(doc, sel)
        armed = st.session_state.get("ax_del_armed")
        if armed is not None and armed != sel:
            st.session_state.pop("ax_del_armed", None)   # selection moved on — disarm
            armed = None
        h1, h2, h3, h4 = st.columns([6, 1, 1, 1])
        h1.subheader(f"`{sel}`")
        if h2.button(":material/arrow_upward:", key="ax_up", help="Move up"):
            axes_io.move_field(doc, sel, -1); st.rerun()
        if h3.button(":material/arrow_downward:", key="ax_down", help="Move down"):
            axes_io.move_field(doc, sel, +1); st.rerun()
        if armed == sel:
            if h4.button(":material/delete_forever:", key="ax_del",
                         help="Click again to delete"):
                axes_io.delete_field(doc, sel)
                st.session_state.pop("axes_sel", None)
                st.session_state.pop("ax_del_armed", None)
                st.rerun()
        elif h4.button(":material/delete:", key="ax_del", help="Delete axis"):
            st.session_state.ax_del_armed = sel
            st.rerun()

        FORM_KINDS = [k for k in fields_mod.KINDS if k != "object"]
        KIND_LABELS = {
            "single": "single — the judge picks exactly one value",
            "multi": "multi — the judge picks a set of values",
            "bool": "bool — yes / no",
            "free": "free — any text (open vocabulary, no fixed values)",
        }
        DF_LABELS = {
            "user_turn": "user_turn — the user's message",
            "response": "response — the assistant's answer",
            "scenario": "scenario — the situation the conversation is about",
            "structure": "structure — the conversation's shape (e.g. has a pushback turn)",
            "meta": "meta — about the record itself (e.g. its language)",
        }
        kind = entry.get("kind", "single")
        g1, g2 = st.columns(2)
        new_name = g1.text_input("Name", value=sel, key=f"ax_name_{sel}_{rev}")
        g1.caption("snake_case; becomes the key in each record's tag JSON")
        if new_name != sel and new_name:
            if new_name in names:
                st.error(f"an axis named `{new_name}` already exists")
            else:
                axes_io.set_attr(doc, sel, "name", new_name)
                st.session_state.axes_sel = new_name
                for k in list(st.session_state):
                    if isinstance(k, str) and k.startswith("ax_") and f"_{sel}_" in k + "_":
                        st.session_state.pop(k)
                st.rerun()
        if kind in FORM_KINDS:
            new_kind = g2.selectbox(
                "Kind", FORM_KINDS, index=FORM_KINDS.index(kind), key=f"ax_kind_{sel}_{rev}",
                format_func=lambda k: KIND_LABELS.get(k, k),
                help="how many answers the judge gives for this axis")
            if new_kind != kind:
                axes_io.set_attr(doc, sel, "kind", new_kind); st.rerun()
        else:
            g2.caption(f"kind `{kind}` — edit via Raw YAML")
        g3, g4 = st.columns(2)
        df = entry.get("derived_from", "scenario")
        new_df = g3.selectbox("Judge reads from", list(fields_mod.DERIVED_FROM),
                              index=list(fields_mod.DERIVED_FROM).index(df),
                              key=f"ax_df_{sel}_{rev}",
                              format_func=lambda k: DF_LABELS.get(k, k),
                              help="which part of the conversation the judge looks "
                                   "at to decide this axis's value")
        if new_df != df:
            axes_io.set_attr(doc, sel, "derived_from", new_df); st.rerun()
        req = bool(entry.get("required", True))
        new_req = g4.checkbox("Required — judge must always output it", value=req,
                              key=f"ax_req_{sel}_{rev}")
        if new_req != req:
            axes_io.set_attr(doc, sel, "required", new_req); st.rerun()
        hint = entry.get("prompt_hint", "")
        new_hint = st.text_area("Prompt hint (shown to the judge — as long as it "
                                "needs to be)",
                                value=hint, key=f"ax_hint_{sel}_{rev}", height=68)
        if new_hint != hint:
            axes_io.set_attr(doc, sel, "prompt_hint", new_hint); st.rerun()

        # ---- values (hidden for bool/free) ----
        values = [str(v) for v in (entry.get("values") or [])]
        if kind in ("single", "multi"):
            st.markdown("**Allowed values**")
            for i, val in enumerate(values):
                v1, v2 = st.columns([8, 1])
                v1.code(val, language=None)
                if v2.button("✕", key=f"ax_valdel_{sel}_{i}_{rev}"):
                    pruned = axes_io.set_values(doc, sel,
                                                values[:i] + values[i + 1:])
                    if pruned:
                        st.toast(f"also removed quota entries for: {pruned}")
                    st.rerun()
            a1, a2 = st.columns([8, 1])
            new_val = a1.text_input("add value", key=f"ax_valadd_{sel}_{rev}",
                                    label_visibility="collapsed",
                                    placeholder="add a value…")
            if a2.button("Add", key=f"ax_valaddbtn_{sel}_{rev}"):
                if new_val and new_val not in values:
                    axes_io.set_values(doc, sel, values + [new_val]); st.rerun()
                elif new_val:
                    st.error("value already present (values are a set)")
            st.caption("the judge must pick from these; removing one that a quota "
                       "references removes that quota entry too")

        # ---- quota editor ----
        RULES = ["none", "require_all_values", "min_share", "max_share",
                 "max_share_each", "band_each"]
        target = dict(entry.get("target") or {})
        st.markdown("**Coverage quota** *(optional — checked by the report, never "
                    "blocks tagging)*")
        if len([r for r in RULES[1:] if r in target]) > 1:
            st.caption("this axis has a combined multi-rule quota — edit via Raw YAML")
        else:
            RULE_LABELS = {
                "none": "none — no quota for this axis",
                "require_all_values": "require_all_values — every value must appear "
                                      "at least once in the corpus",
                "min_share": "min_share — a minimum share for chosen values "
                             "(e.g. Hidden ≥ 20%)",
                "max_share": "max_share — a maximum share for chosen values",
                "max_share_each": "max_share_each — one cap that applies to every value",
                "band_each": "band_each — every value inside a [low, high] share band",
            }
            current = next((r for r in RULES[1:] if r in target), "none")
            rule = st.selectbox("Rule", RULES, index=RULES.index(current),
                                key=f"ax_rule_{sel}_{rev}",
                                format_func=lambda k: RULE_LABELS.get(k, k),
                                help="a target the report checks the tagged corpus "
                                     "against — it flags misses, never blocks tagging")
            new_target: dict | None
            if rule == "none":
                new_target = None
            elif rule == "require_all_values":
                new_target = {"require_all_values": True}
            elif rule in ("min_share", "max_share"):
                shares = dict(target.get(rule) or {})
                picked = st.multiselect("Values with a quota", values,
                                        default=[v for v in shares if v in values],
                                        key=f"ax_qvals_{sel}_{rev}")
                new_shares = {}
                for v in picked:
                    new_shares[v] = st.number_input(
                        f"{rule} · {v}", 0.0, 1.0, float(shares.get(v, 0.1)), 0.05,
                        key=f"ax_qs_{sel}_{rule}_{v}_{rev}")
                new_target = {rule: new_shares} if new_shares else None
            elif rule == "max_share_each":
                cap = st.number_input("Cap for every value", 0.0, 1.0,
                                      float(target.get("max_share_each", 0.12)), 0.01,
                                      key=f"ax_qcap_{sel}_{rev}")
                new_target = {"max_share_each": cap}
            else:  # band_each
                band = list(target.get("band_each") or [0.25, 0.40])
                if len(band) != 2:
                    band = [0.25, 0.40]
                b1c, b2c = st.columns(2)
                lo = b1c.number_input("Low", 0.0, 1.0, float(band[0]), 0.05,
                                      key=f"ax_qlo_{sel}_{rev}")
                hi = b2c.number_input("High", 0.0, 1.0, float(band[1]), 0.05,
                                      key=f"ax_qhi_{sel}_{rev}")
                new_target = {"band_each": [lo, hi]}
            if new_target != (dict(entry.get("target")) if entry.get("target") else None):
                axes_io.set_target(doc, sel, new_target)
                st.rerun()
        st.caption("Quota edits are **free** — re-Analyze only, no re-tagging.")

# ---------------------------------------------------------------- cost + warnings
try:
    change = axes_io.classify_change(disk_doc, doc)
except (ValueError, TypeError):
    change = None                                # draft transiently invalid
if change == "identity":
    st.warning(":material/paid: **These edits change what the judge tags** — the "
               "next **Tag** will start a fresh bundle and re-tag the corpus (one "
               "cheap LLM call per record). Your old tags are kept untouched in "
               "their own bundle.")
elif change in ("quota_only", "analysis_only"):
    st.info("These edits are **free** — quotas / analysis config only. Re-run "
            "**Analyze** to refresh the report; no re-tagging.")

for w in axes_io.coupling_warnings(disk_doc, doc):
    st.warning(f":material/link_off: {w['message']}")
for old, new in axes_io.renames(disk_doc, doc):
    if any(old in pair for pair in axes_io.stale_important_pairs(doc)):
        if st.button(f"Update `important_pairs`: `{old}` → `{new}`",
                     key=f"fixpair_{old}"):
            axes_io.update_important_pairs(doc, old, new)
            st.rerun()
if axes_io.stale_important_pairs(doc):
    if st.button("Remove stale `important_pairs` entries"):
        axes_io.prune_important_pairs(doc)
        st.rerun()

# ---------------------------------------------------------------- raw escape hatch
with st.expander(":material/code: Raw YAML — full file, incl. the `analysis:` "
                 "block (metrics selection)"):
    st.caption("The escape hatch for anything the form doesn't cover — the "
               "`analysis:` block, `object` kinds, bulk edits. **Apply** replaces "
               "the draft above; parse errors leave it untouched.")
    raw_dump = axes_io.dump_text(doc)
    raw = st.text_area("axes YAML", value=raw_dump, height=400,
                       key=f"axes_raw_{rev}_{zlib.crc32(raw_dump.encode())}",
                       label_visibility="collapsed")
    if st.button("Apply raw YAML"):
        try:
            parsed = axes_io.load_text(raw)
        except Exception as e:                       # noqa: BLE001 — show any parse error
            st.error(f"not applied — YAML parse error: {e}")
        else:
            if not axes_io.structurally_editable(parsed):
                st.error("not applied — the axes file must be a YAML mapping with a "
                         "non-empty `fields:` list.")
            else:
                st.session_state.axes_draft = parsed
                st.session_state.axes_rev = st.session_state.get("axes_rev", 0) + 1
                st.rerun()

# ---------------------------------------------------------------- save
errors = axes_io.validate_doc(doc)
c1, c2, c3 = st.columns([1, 1, 2])
if c1.button(":material/save: Validate & Save", type="primary", disabled=bool(errors)):
    axes_io.save_doc(doc, axes_io.AXES_PATH)
    st.success(f"Saved `{axes_io.AXES_PATH.name}`. Go to **Run diversity → Tag** "
               "to apply the new schema (a fresh bundle if the tagging inputs "
               "changed).")
if c2.button(":material/restart_alt: Discard draft & reload from disk"):
    st.session_state.pop("axes_draft", None)
    st.session_state.axes_rev = st.session_state.get("axes_rev", 0) + 1
    st.rerun()
for e in errors:
    st.error(f"invalid — fix before saving: {e}")
c3.caption("checks the schema first (bad quota / unknown kind = nothing written), "
           "then saves `evals/dad_axes.yaml`. Warnings above are advisory — they "
           "never block saving. Reload throws away every unsaved edit above and "
           "re-reads `evals/dad_axes.yaml`.")

# ---------------------------------------------------------------- judge prompts
st.divider()
st.subheader("Judge prompts")
st.caption("The two LLM prompts of the diversity judge. They are ordinary text "
           "files — edit and save them here, no code involved.")


def _prompt_editor(title: str, path, cost_caption: str, key_base: str,
                   required_tokens: tuple[str, ...] = ()) -> None:
    with st.expander(title):
        st.caption(cost_caption)
        if required_tokens:
            tokens = " and ".join(f"`{t}`" for t in required_tokens)
            st.caption(f":material/warning: This prompt must keep the {tokens} "
                       "placeholder(s) — the pipeline fills them in automatically "
                       "at run time, and tagging/analysis fails without them. Edit "
                       "the instructions around them freely.")
        disk_text = path.read_text()
        text = st.text_area("prompt text", value=disk_text, height=300,
                            key=f"{key_base}_{zlib.crc32(disk_text.encode())}",
                            label_visibility="collapsed")
        missing = [t for t in required_tokens if t not in text]
        if missing:
            st.error("missing required placeholder(s): "
                     + ", ".join(f"`{t}`" for t in missing)
                     + " — saving is blocked until they are restored.")
        elif text != disk_text:
            st.warning("modified — not saved yet")
        if st.button(f"Save {path.name}", key=f"{key_base}_save",
                     disabled=bool(missing)):
            if not text.strip():
                st.error("not saved — the prompt cannot be empty.")
            else:
                axes_io.save_text(text, path)
                st.success(f"Saved `{path.name}`.")
                st.rerun()


_prompt_editor(
    ":material/edit_note: Extraction judge prompt (`dad_category_extract.txt`)",
    DEFAULT_EXTRACT_PROMPT,
    "The system prompt of the judge that **tags** each conversation. The axes "
    "schema above is rendered into it automatically. **Editing it changes the "
    "tags** — the next **Tag** starts a fresh bundle and re-tags the corpus "
    "(paid); old tags stay untouched in their own bundle.",
    "prompt_extract",
    required_tokens=(extract_mod.FIELDS_TOKEN, extract_mod.KEYS_TOKEN))
_prompt_editor(
    ":material/edit_note: Synthesis prompt (`dad_holistic_synthesis.txt`)",
    DEFAULT_SYNTH_PROMPT,
    "The prompt for the one LLM call that writes the report's narrative summary. "
    "Editing it is **free** — just re-run **Analyze**; no re-tagging.",
    "prompt_synth",
    required_tokens=(synthesize_mod.STATS_TOKEN,))

# ---------------------------------------------------------------- SDF (filler)
with st.expander("SDF axes"):
    st.caption("SDF documents don't have a categorical axes file yet — the SDF "
               "pipeline's diversity story is still settling. When it lands, its "
               "axes will be editable here the same way.")
