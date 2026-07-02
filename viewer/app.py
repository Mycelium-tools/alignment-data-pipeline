"""Run viewer entrypoint: streamlit run viewer/app.py"""

import streamlit as st

st.set_page_config(page_title="Alignment Data Pipeline — Run Viewer", layout="wide")

nav = st.navigation([
    st.Page("ui_pages/runs_index.py", title="Runs", icon="📋", default=True),
    st.Page("ui_pages/run_detail.py", title="Run detail", icon="🔍"),
    st.Page("ui_pages/document_detail.py", title="Document lineage", icon="🧬"),
    st.Page("ui_pages/compare.py", title="Compare runs", icon="⚖️"),
])
nav.run()
