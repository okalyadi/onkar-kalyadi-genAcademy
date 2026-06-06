"""Tab 3: Historical Performance.

Shows lifetime performance metric cards (invested, sells, current value, total
return, XIRR), the full transaction table, and an optional cumulative cashflow
chart.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from utils.portfolio_math import (
    PortfolioError,
    build_current_holdings,
    compute_performance_metrics,
    compute_xirr,
    cumulative_cashflow_series,
)


def render() -> None:
    st.header("📈 Historical Performance")

    df = st.session_state.get("transactions")
    if df is None:
        st.info("Please upload a CSV in the **Data Upload** tab first.")
        return

    # Reuse cached holdings/metrics if Tab 2 already computed them.
    holdings = st.session_state.get("holdings")
    metrics = st.session_state.get("metrics")
    if holdings is None or metrics is None:
        try:
            with st.spinner("Computing performance and fetching live prices..."):
                holdings, _failed = build_current_holdings(df)
                metrics = compute_performance_metrics(df, holdings)
                st.session_state["holdings"] = holdings
                st.session_state["metrics"] = metrics
        except PortfolioError as exc:
            st.error(f"❌ Could not compute performance: {exc}")
            return

    current_value = metrics["current_value"]
    xirr = compute_xirr(df, current_value)

    # --- Metric cards ---------------------------------------------------
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Investment (lifetime)", f"${metrics['total_investment']:,.2f}")
    c2.metric("Total Sells (lifetime)", f"${metrics['total_sells']:,.2f}")
    c3.metric("Current Portfolio Value", f"${current_value:,.2f}")

    c4, c5 = st.columns(2)
    c4.metric(
        "Total Return",
        f"${metrics['total_return']:,.2f}",
        delta=f"{metrics['total_return_pct']:+.2f}%",
    )
    if xirr is not None:
        c5.metric("XIRR (annualized)", f"{xirr * 100:.2f}%")
    else:
        c5.metric("XIRR (annualized)", "N/A")
        st.caption(
            "ℹ️ XIRR could not be computed — this usually means all cashflows have "
            "the same sign or share a single date."
        )

    st.caption(
        "Total Return = Total Sells + Current Value − Total Investment. "
        "XIRR uses every Buy (−) and Sell (+) cashflow plus current value as a final inflow today."
    )

    # --- Optional cumulative cashflow chart ----------------------------
    st.subheader("Net Capital Deployed Over Time")
    try:
        series = cumulative_cashflow_series(df)
        if not series.empty:
            fig = px.area(
                series,
                x="date",
                y="cumulative_net_invested",
                labels={"date": "Date", "cumulative_net_invested": "Net Invested ($)"},
            )
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Cumulative buys minus sells — the net capital you've had deployed over time.")
    except Exception as exc:  # pragma: no cover - chart is best-effort
        st.caption(f"(Cashflow chart unavailable: {exc})")

    # --- Transaction table ---------------------------------------------
    st.subheader("Transaction History")
    display_df = df.copy().sort_values("date")
    display_df["amount"] = display_df["quantity"] * display_df["price"]
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.rename(
        columns={
            "ticker": "Ticker",
            "date": "Date",
            "transaction_type": "Type",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
        }
    )
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
