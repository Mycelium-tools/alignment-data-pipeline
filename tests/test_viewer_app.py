"""The viewer nav registers real page files — a typo'd st.Page path fails at
click time in streamlit, so pin registration at test time by source scan."""

import re
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[1] / "viewer"


def test_every_registered_page_file_exists_and_nav_is_sectioned():
    src = (VIEWER / "app.py").read_text()
    pages = re.findall(r'st\.Page\("([^"]+)"', src)
    assert pages, "no st.Page registrations found"
    for rel in pages:
        assert (VIEWER / rel).exists(), f"registered page missing: {rel}"
    assert "ui_pages/edit_axes.py" in pages
    for section in ('"Runs"', '"Judge"', '"Diversity"'):
        assert section in src, f"nav section {section} missing"
