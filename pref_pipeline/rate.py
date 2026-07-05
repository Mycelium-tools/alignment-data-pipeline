"""Blind A/B rating app for preference pairs: streamlit run pref_pipeline/rate.py

Shows each pair with arm identities hidden; which arm is Response 1 vs 2 is
fixed per pair (left_arm in pairs.jsonl), so the order carries no signal but
never flips on reload. Every choice appends to ratings/ratings.jsonl and
rebuilds final/preferences.jsonl.
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from pref_pipeline import prefdata

st.set_page_config(page_title="Preference Rating", layout="wide")

runs = prefdata.list_runs()
if not runs:
    st.warning(
        "No preference runs with pairs found under outputs/pref/runs/.\n\n"
        "Generate pairs first: `python pref_pipeline/run.py --prompts <file.jsonl>`"
    )
    st.stop()

with st.sidebar:
    run_dir = st.selectbox("Run", runs, format_func=lambda p: p.name)
    rater = st.text_input("Rater", value=os.environ.get("USER", "rater")).strip() or "rater"

pairs = prefdata.load_pairs(run_dir)
ratings = prefdata.load_ratings(run_dir)
pending = prefdata.pending_pairs(pairs, ratings, rater)
done = len(pairs) - len(pending)

with st.sidebar:
    st.progress(done / len(pairs) if pairs else 0.0, text=f"{done}/{len(pairs)} rated")
    counts = prefdata.arm_win_counts(pairs, ratings)
    if counts:
        st.caption("Choices so far (all raters)")
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            st.caption(f"{name}: {n}")

if not pending:
    st.success(f"All {len(pairs)} pairs rated by {rater}.")
    st.caption(f"Preference records: {run_dir / 'final' / 'preferences.jsonl'}")
    st.stop()

pair = pending[0]
st.caption(f"Pair {done + 1} of {len(pairs)} — {pair['pair_id']}")
with st.chat_message("user"):
    st.markdown(pair["user_message"])

left, right = prefdata.sides(pair)
col1, col2 = st.columns(2)
for col, title, arm in ((col1, "Response 1", left), (col2, "Response 2", right)):
    with col:
        st.subheader(title)
        with st.container(border=True):
            st.markdown(pair[f"response_{arm}"])

note = st.text_input("Note (optional)", key=f"note_{pair['pair_id']}")

b1, b2, b3, b4 = st.columns(4)
choice = None
if b1.button("⬅ 1 is better", type="primary", use_container_width=True):
    choice = "left"
if b2.button("2 is better ➡", type="primary", use_container_width=True):
    choice = "right"
if b3.button("Tie", use_container_width=True):
    choice = "tie"
if b4.button("Both bad", use_container_width=True):
    choice = "both_bad"

if choice:
    prefdata.record_rating(run_dir, pair, rater, choice, note)
    st.rerun()
