"""Combined Judge page: toggle between the DAD judge and the SDF judge.
The two are different instruments (conversations vs documents) but live under one section."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer.ui_pages import judge_dad, judge_sdf

st.title("Judge")

mode = st.segmented_control(
    "Judge", ["DAD", "SDF"], default="DAD", label_visibility="collapsed",
    key="judge_mode",
)

if mode == "SDF":
    judge_sdf.render()
else:
    judge_dad.render()
