"""Smoke tests: every dashboard page renders without an exception for several as-of months.

Uses Streamlit's headless AppTest. Pages read the local database (seeded from the
sample data on first run); nothing is written by these tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
PAGES = sorted((Path(__file__).resolve().parents[1] / "pages").glob("*.py"))


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
@pytest.mark.parametrize("as_of", ["2026-04", "2026-07", "2026-10", "2027-03"])
def test_page_renders(page, as_of):
    at = st_testing.AppTest.from_file(str(page), default_timeout=60)
    at.session_state["as_of"] = as_of
    at.run()
    assert not at.exception, [e.value for e in at.exception]
