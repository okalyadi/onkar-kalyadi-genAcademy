"""Tab 2: Consolidated Portfolio View.

Computes current holdings via FIFO, fetches live prices, and shows an
allocation pie chart, total value metric, the stock-wise breakdown table, and a
Groq-generated portfolio health summary.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from utils import llm_agent
from utils.portfolio_math import (
    PortfolioError,
    build_current_holdings,
    compute_performance_metrics,
    compute_xirr,
)


def _ensure_holdings():
    """Compute (and cache in session_state) holdings + metrics + failures.

    Returns ``(holdings, metrics, failed_tickers)`` or raises PortfolioError.
    """
    df = st.session_state.get("transactions")
    holdings, failed = build_current_holdings(df)
    metrics = compute_performance_metrics(df, holdings)
    st.session_state["holdings"] = holdings
    st.session_state["metrics"] = metrics
    st.session_state["price_failures"] = failed
    return holdings, metrics, failed


def render() -> None:
    st.header("📊 Consolidated Portfolio View")

    df = st.session_state.get("transactions")
    if df is None:
        st.info("Please upload a CSV in the **Data Upload** tab first.")
        return

    try:
        with st.spinner("Computing FIFO holdings and fetching live prices..."):
            holdings, metrics, failed = _ensure_holdings()
    except PortfolioError as exc:
        st.error(f"❌ Could not compute holdings: {exc}")
        return

    if failed:
        st.warning(
            "⚠️ Could not fetch a live price for: "
            + ", ".join(failed)
            + ". Their cost basis is used as a placeholder price."
        )

    if holdings.empty:
        st.info(
            "You have no open positions — every purchased share appears to have been sold. "
            "Check the **Historical Performance** tab for realized results."
        )
        return

    # --- Total value metric --------------------------------------------
    total_value = float(holdings["market_value"].sum())
    total_unrealized = float(holdings["unrealized_gain"].sum())
    cost_basis = float(holdings["cost_basis_total"].sum())
    unrl_pct = (total_unrealized / cost_basis * 100.0) if cost_basis else 0.0

    c1, c2 = st.columns(2)
    c1.metric("Total Current Portfolio Value", f"${total_value:,.2f}")
    c2.metric(
        "Total Unrealized Gain/Loss",
        f"${total_unrealized:,.2f}",
        delta=f"{unrl_pct:+.2f}%",
    )

    # --- Allocation pie chart ------------------------------------------
    st.subheader("Portfolio Allocation")
    fig = px.pie(
        holdings,
        names="ticker",
        values="market_value",
        hole=0.4,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), legend_title_text="Ticker")
    st.plotly_chart(fig, use_container_width=True)

    # --- Holdings table -------------------------------------------------
    st.subheader("Holdings Breakdown")
    table = holdings[
        [
            "ticker",
            "quantity",
            "avg_cost_basis",
            "current_price",
            "market_value",
            "unrealized_gain",
            "unrealized_gain_pct",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "quantity": "Quantity",
            "avg_cost_basis": "Avg Cost Basis",
            "current_price": "Current Price",
            "market_value": "Market Value",
            "unrealized_gain": "Unrealized Gain/Loss",
            "unrealized_gain_pct": "Unrealized %",
        }
    )
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quantity": st.column_config.NumberColumn(format="%.4g"),
            "Avg Cost Basis": st.column_config.NumberColumn(format="$%.2f"),
            "Current Price": st.column_config.NumberColumn(format="$%.2f"),
            "Market Value": st.column_config.NumberColumn(format="$%.2f"),
            "Unrealized Gain/Loss": st.column_config.NumberColumn(format="$%.2f"),
            "Unrealized %": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

    # --- AI portfolio health summary -----------------------------------
    st.subheader("🤖 AI Portfolio Health Summary")
    if not llm_agent.is_configured():
        st.warning(
            "⚠️ `GROQ_API_KEY` is not set, so the AI summary is unavailable. "
            "Add it to your `.env` file to enable AI features."
        )
    else:
        if st.button("Generate AI summary", key="gen_summary"):
            try:
                with st.spinner("Asking the AI analyst..."):
                    xirr = compute_xirr(df, total_value)
                    summary = llm_agent.generate_portfolio_summary(holdings, metrics, xirr)
                st.session_state["portfolio_summary"] = summary
            except llm_agent.LLMConfigError as exc:
                st.warning(f"⚠️ {exc}")
            except Exception as exc:
                st.error(f"❌ AI summary failed: {exc}")

        if st.session_state.get("portfolio_summary"):
            st.info(st.session_state["portfolio_summary"])
        st.caption("ℹ️ " + llm_agent.DISCLAIMER)
