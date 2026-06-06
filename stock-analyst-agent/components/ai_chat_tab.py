"""Tab 4: AI Analyst Chat.

Interactive chat grounded in the user's portfolio. Maintains history in session
state and passes transactions, holdings, metrics, allocations and unrealized P/L
as context. For "why is X down today" questions it fetches recent price moves
from yfinance before answering.
"""

from __future__ import annotations

import re

import streamlit as st

from utils import llm_agent
from utils.portfolio_math import (
    build_current_holdings,
    compute_performance_metrics,
    compute_xirr,
    fetch_quotes,
)

SUGGESTED_QUESTIONS = [
    "Summarize my historical trading performance.",
    "Am I over-concentrated in any stock?",
    "Which stocks are driving most of my gains?",
    "What are my worst-performing holdings?",
    "Why is my portfolio down today?",
]

_TODAY_MOVE_PATTERN = re.compile(r"\b(today|down today|up today|moved today|daily move|drop)\b", re.IGNORECASE)


def _maybe_daily_move_context(user_message: str, holdings) -> str | None:
    """If the user asks about today's movement, fetch & summarize daily moves.

    Returns a text block of per-ticker daily moves, or None if not applicable.
    """
    if holdings is None or holdings.empty:
        return None
    if not _TODAY_MOVE_PATTERN.search(user_message):
        return None

    quotes = fetch_quotes(tuple(holdings["ticker"].tolist()))
    lines = ["Per-holding daily price move (latest close vs previous close):"]
    contributions = []
    for row in holdings.itertuples(index=False):
        q = quotes.get(row.ticker, {})
        if not q.get("ok"):
            lines.append(f"- {row.ticker}: price data unavailable")
            continue
        day_change = q.get("day_change", float("nan"))
        day_pct = q.get("day_change_pct", float("nan"))
        # Dollar impact on the portfolio = per-share move * shares held.
        dollar_impact = day_change * row.quantity
        contributions.append((row.ticker, dollar_impact))
        lines.append(
            f"- {row.ticker}: {day_pct:+.2f}% on the day "
            f"(${day_change:+.2f}/share), portfolio impact ${dollar_impact:+,.2f}"
        )
    if contributions:
        total_impact = sum(c for _, c in contributions)
        lines.append(f"Total estimated portfolio day move: ${total_impact:+,.2f}")
    lines.append(
        "NOTE: Only price data is available — no news/earnings context. "
        "Explain the move strictly from these numbers."
    )
    return "\n".join(lines)


def _handle_user_message(user_message: str) -> None:
    """Append the user message, generate a grounded response, append it."""
    st.session_state["chat_history"].append({"role": "user", "content": user_message})

    df = st.session_state.get("transactions")
    holdings = st.session_state.get("holdings")
    metrics = st.session_state.get("metrics")

    # Compute on demand if the user jumped straight to chat.
    if df is not None and (holdings is None or metrics is None):
        try:
            holdings, _failed = build_current_holdings(df)
            metrics = compute_performance_metrics(df, holdings)
            st.session_state["holdings"] = holdings
            st.session_state["metrics"] = metrics
        except Exception:
            holdings, metrics = None, None

    xirr = compute_xirr(df, metrics["current_value"]) if (df is not None and metrics) else None
    extra = _maybe_daily_move_context(user_message, holdings)

    try:
        response = llm_agent.generate_chat_response(
            history=st.session_state["chat_history"][:-1],
            user_message=user_message,
            holdings=holdings,
            metrics=metrics,
            xirr=xirr,
            transactions=df,
            extra_context=extra,
        )
    except llm_agent.LLMConfigError as exc:
        response = f"⚠️ {exc}"
    except Exception as exc:
        response = f"❌ Sorry, the AI request failed: {exc}"

    st.session_state["chat_history"].append({"role": "assistant", "content": response})


def render() -> None:
    st.header("💬 AI Analyst Chat")

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    df = st.session_state.get("transactions")
    if df is None:
        st.info("Please upload a CSV in the **Data Upload** tab first.")
        return

    if not llm_agent.is_configured():
        st.warning(
            "⚠️ `GROQ_API_KEY` is not set, so the chat is disabled. "
            "Add it to your `.env` file to enable AI features."
        )
        return

    st.caption(
        "Ask about your portfolio. Answers are grounded only in your uploaded data, "
        "computed metrics, and yfinance prices. " + llm_agent.DISCLAIMER
    )

    # --- Suggested questions -------------------------------------------
    with st.expander("💡 Example questions", expanded=len(st.session_state["chat_history"]) == 0):
        cols = st.columns(2)
        for i, q in enumerate(SUGGESTED_QUESTIONS):
            if cols[i % 2].button(q, key=f"suggest_{i}", use_container_width=True):
                _handle_user_message(q)
                st.rerun()

    col_a, col_b = st.columns([1, 5])
    if col_a.button("🗑️ Clear chat"):
        st.session_state["chat_history"] = []
        st.rerun()

    # --- Render history -------------------------------------------------
    for turn in st.session_state["chat_history"]:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    # --- Chat input -----------------------------------------------------
    prompt = st.chat_input("Ask about your portfolio...")
    if prompt:
        _handle_user_message(prompt)
        st.rerun()
