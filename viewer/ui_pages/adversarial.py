"""Adversarial review view (rendered inside the combined Judge page via render()).
Run the judge on controlled same-issue variant families and see whether known blindspots
(verbosity, fabricated specificity, species-swap, sycophancy) move the scores they
shouldn't. The suite grows — add families in evals/adversarial_cases.yaml. Gates
rubric/prompt/model changes."""

import sys
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals import adversarial, judge
from shared import api
from viewer import loader

CASES_PATH = adversarial.DEFAULT_CASES_PATH
KNOWN_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro", "claude-haiku-4-5",
                "claude-sonnet-4-6", "claude-opus-4-8"]


@st.cache_resource
def _api_ready() -> bool:
    api.init(str(loader.REPO_ROOT / "config.yaml"))
    return True


def render() -> None:
    st.caption("Same welfare issue, one axis mutated. The judge should not be fooled by "
               "that axis — we check relative scores between variants, and the suite "
               "grows with each blindspot found.")

    cases = yaml.safe_load(CASES_PATH.read_text())
    family_ids = [f["id"] for f in cases["families"]]

    with st.sidebar:
        panel = st.multiselect("Judge panel", KNOWN_MODELS, default=["gemini-2.5-flash"],
                               accept_new_options=True)
        chosen = st.multiselect("Families", family_ids, default=family_ids)
        run_clicked = st.button(":material/security: Run adversarial review", type="primary",
                                disabled=not (panel and chosen))

    # Family reference — always visible so the suite reads as documentation of blindspots
    for fam in cases["families"]:
        with st.expander(f"{fam['id']} — {fam['blindspot'].strip().splitlines()[0]}"):
            st.caption(f"Welfare issue: {fam['welfare_issue']}")
            st.markdown(f"**Blindspot:** {fam['blindspot']}")
            st.markdown(f"**Variants:** {', '.join(v['id'] for v in fam['variants'])}")
            n_exp = sum(len(v.get("expect", [])) for v in fam["variants"])
            st.caption(f"{n_exp} expectations")

    if run_clicked:
        _api_ready()
        rubric = judge.load_rubric()
        principles = judge.load_principles()
        selected = [f for f in cases["families"] if f["id"] in chosen]
        with st.status(f"Running {len(chosen)} family(ies) x {len(panel)} model(s)...",
                       expanded=True) as status:
            results = []
            system = judge.build_system_prompt(rubric, principles)
            for model in panel:
                for fam in selected:
                    st.write(f"{model} · {fam['id']}")
                    results.append(adversarial.run_family(fam, model, rubric, principles, system))
            status.update(label="Done", state="complete", expanded=False)
        st.session_state.adv_results = results

    for r in st.session_state.get("adv_results", []):
        icon = ":material/check_circle:" if r["passed"] else ":material/cancel:"
        st.subheader(f"{icon} {r['family']} · {r['model']}")
        for c in r["checks"]:
            mark = ":green[ok]" if c["passed"] else ":red[XX]"
            b = f" vs {c.get('b')}" if "b" in c else ""
            st.markdown(f"{mark} `{c['op']}({c['a']}{b}).{c['field']}` — {c['detail']}")
        for vid, err in r["errors"].items():
            st.error(f"judge error on {vid}: {err}")
