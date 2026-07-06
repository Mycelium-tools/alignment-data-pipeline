"""Run viewer entrypoint: streamlit run viewer/app.py"""

import streamlit as st

st.set_page_config(page_title="Alignment Data Pipeline — Run Viewer", layout="wide")

# Default cursor (not text/pointer) on dropdown inputs and options,
# and left-align the document-row buttons so they read as list rows.
st.html("""<style>
div[data-baseweb="select"] input,
div[data-baseweb="select"] div,
ul[data-baseweb="menu"] li,
[role="listbox"] [role="option"] { cursor: default !important; }
div[data-testid="stButton"] button,
button[data-testid^="stBaseButton"] { justify-content: flex-start !important; text-align: left !important; width: 100%; }
div[data-testid="stButton"] button > div { justify-content: flex-start !important; }
div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] { text-align: left; width: 100%; }
div[data-testid="stButton"] button p { text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
</style>""")

nav = st.navigation([
    st.Page("ui_pages/lineage.py", title="Document lineage", icon=":material/account_tree:", default=True),
    st.Page("ui_pages/compare.py", title="Compare runs", icon=":material/compare_arrows:"),
    st.Page("ui_pages/run_list.py", title="Run list", icon=":material/list:"),
    st.Page("ui_pages/judge.py", title="Judge", icon=":material/gavel:"),
])
nav.run()
