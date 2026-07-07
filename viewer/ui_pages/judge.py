"""Combined Judge page: toggle between the DAD judge and the SDF judge.
The two are different instruments (conversations vs documents) but live under one section."""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer.ui_pages import adversarial, judge_batch, judge_dad, judge_sdf

st.title("Judge")

mode = st.segmented_control(
    "Judge", ["DAD", "SDF", "Adversarial review", "Score a run"], default="DAD",
    label_visibility="collapsed", key="judge_mode",
)

if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("VERTEX_PROJECT")):
    st.caption(":material/key: No Gemini credentials found — add `GEMINI_API_KEY` or "
               "`VERTEX_PROJECT` to `.env` to run Gemini judges (README → Evals → Judge "
               "API keys). `claude-*` judges use `ANTHROPIC_API_KEY`.")

if mode == "SDF":
    judge_sdf.render()
elif mode == "Adversarial review":
    adversarial.render()
elif mode == "Score a run":
    judge_batch.render()
else:
    judge_dad.render()
