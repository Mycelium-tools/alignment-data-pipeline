"""Run viewer entrypoint: streamlit run viewer/app.py"""

import streamlit as st

st.set_page_config(page_title="Alignment Data Pipeline — Run Viewer", layout="wide")

# Default cursor (not text/pointer) on dropdown inputs and options.
st.html("""<style>
div[data-baseweb="select"] input,
div[data-baseweb="select"] div,
ul[data-baseweb="menu"] li,
[role="listbox"] [role="option"] { cursor: default !important; }
</style>""")

nav = st.navigation([
    st.Page("ui_pages/lineage.py", title="Document lineage", icon=":material/account_tree:", default=True),
    st.Page("ui_pages/compare.py", title="Compare runs", icon=":material/compare_arrows:"),
    st.Page("ui_pages/run_list.py", title="Run list", icon=":material/list:"),
])
nav.run()
