"""SDF judge view (rendered inside the combined Judge page via render()). Placeholder:
the SDF judge is a separate instrument from the DAD judge (documents, not conversations)
and its rubric is not yet designed."""

import streamlit as st


def render() -> None:
    st.info(
        "The SDF judge is not built yet — it is a separate instrument from the DAD judge, "
        "because SDF records are pretraining-style **documents**, not advice conversations, "
        "and their virtues differ."
    )
    st.markdown("""
Planned document-shaped dimensions (spec §10 / design notes):

- **realism / register** — reads like genuine pretraining text of its claimed document type
- **teaching_value** — articulates *why* with tradeoffs, not assertion lists
- **no_outside_world_facts** — penalize specific real-world factual claims beyond the
  source material (they enter pretraining as facts); this replaces unverifiable
  fact-checking with a checkable rule
- **reasoning_fidelity** — decoupled from stance: critical and neutral documents about
  the constitution are corpus targets, not defects
- **cell_adherence** — the document actually is what its generation cell says it is

When `evals/rubric_sdf_v1.yaml` exists, this view will get the same treatment as the
DAD judge: live rubric editing, judge panel, verdict diffs.
""")
