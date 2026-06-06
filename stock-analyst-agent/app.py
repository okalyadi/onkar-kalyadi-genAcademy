"""Stock Analyst Agent — Streamlit entry point.

An AI-powered US stock portfolio analyst. Upload a transaction-history CSV and
explore consolidated holdings, historical performance, and an AI analyst chat
powered by Groq.

Run with:
    uv run streamlit run app.py
"""

from __future__ import annotations

from dotenv import load_dotenv

# Load environment variables from .env before importing modules that read them.
load_dotenv()

import streamlit as st  # noqa: E402

from components import (  # noqa: E402
    ai_chat_tab,
    data_upload_tab,
    historical_performance_tab,
    portfolio_view_tab,
)
from utils import llm_agent  # noqa: E402


def init_session_state() -> None:
    """Initialize session-state keys used across tabs."""
    defaults = {
        "transactions": None,
        "holdings": None,
        "metrics": None,
        "price_failures": [],
        "portfolio_summary": None,
        "chat_history": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def main() -> None:
    st.set_page_config(
        page_title="Stock Analyst Agent",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_state()

    # --- Sidebar --------------------------------------------------------
    with st.sidebar:
        st.title("📈 Stock Analyst Agent")
        st.caption("AI-powered US stock portfolio analysis")
        st.divider()

        if llm_agent.is_configured():
            st.success(f"AI enabled · model: `{llm_agent.get_model_name()}`")
        else:
            st.warning("AI disabled — set `GROQ_API_KEY` in your `.env`.")

        if st.session_state.get("transactions") is not None:
            n = len(st.session_state["transactions"])
            st.info(f"Portfolio loaded: {n} transactions.")
        else:
            st.info("No portfolio loaded yet.")

        st.divider()
        st.caption(
            "⚠️ For educational/informational use only. Not financial advice. "
            "Prices via yfinance may be delayed."
        )

    # --- Tabs -----------------------------------------------------------
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "Data Upload",
            "Consolidated Portfolio View",
            "Historical Performance",
            "AI Analyst Chat",
        ]
    )

    with tab1:
        data_upload_tab.render()
    with tab2:
        portfolio_view_tab.render()
    with tab3:
        historical_performance_tab.render()
    with tab4:
        ai_chat_tab.render()


if __name__ == "__main__":
    main()
