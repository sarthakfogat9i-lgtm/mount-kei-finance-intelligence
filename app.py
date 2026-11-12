"""Mount Kei Finance Intelligence — application entry point.

Run with:  streamlit run app.py

This file only configures Streamlit and registers the pages (listed in src/ui/navigation.py).
Streamlit's built-in navigation is hidden; the sidebar is drawn by src/ui/layout.py so that all
six pages stay visible and the project panel sits at the bottom. Calculations live in src/finance.
"""
from __future__ import annotations

import streamlit as st

from src.ui.navigation import NAV

st.set_page_config(page_title="Mount Kei Finance Intelligence", page_icon="🌳", layout="wide",
                   initial_sidebar_state="expanded")

PAGES = [st.Page(path, title=title, icon=icon, default=(url == ""), **({"url_path": url} if url else {}))
         for _key, path, title, icon, url in NAV]

st.navigation(PAGES, position="hidden").run()
