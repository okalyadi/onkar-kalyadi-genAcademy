"""AI LLM agent wrapper for the Stock Analyst Agent.

Centralizes:
    * Groq or Claude client setup (API key read from environment).
    * Prompt / context construction from portfolio data.
    * Portfolio health summary generation (Tab 2).
    * Chat response generation (Tab 4).
    * Graceful error handling for missing keys, API failures and empty
      responses.

No API key is ever hard-coded; the key is read from the environment (loaded
from ``.env`` via python-dotenv in ``app.py``).
"""

from __future__ import annotations

import os

import pandas as pd

try:
    from groq import Groq
except Exception:  # pragma: no cover - groq should be installed via uv
    Groq = None

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - anthropic is optional
    Anthropic = None

DEFAULT_PROVIDER = "groq"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_CLAUDE_MODEL = "claude-3.1"

DISCLAIMER = (
    "This is informational only and not financial advice."
)

SYSTEM_PROMPT = (
    "You are a careful, data-grounded US stock portfolio analyst assistant. "
    "You ONLY reason from the portfolio data, computed metrics, and any yfinance "
    "price data provided to you in the context. "
    "Rules:\n"
    "- Never invent market news, earnings, or external events. If asked 'why' "
    "something moved and you only have price data, explain strictly from the "
    "price movement provided and say you lack news context.\n"
    "- Do not make explicit buy/sell recommendations. You may make general, "
    "neutral risk observations (e.g. concentration risk).\n"
    "- If you don't have enough information to answer, say so plainly.\n"
    "- Be concise, practical, and specific. Use the actual numbers from the "
    "context.\n"
    "- Always include a brief disclaimer that this is not financial advice."
)


class LLMConfigError(Exception):
    """Raised when the Groq client cannot be configured (e.g. missing key)."""


def get_ai_provider() -> str:
    """Return the configured AI provider name."""
    return os.getenv("AI_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER


def get_model_name() -> str:
    """Return the configured model name for the selected AI provider."""
    provider = get_ai_provider()
    if provider == "claude":
        return os.getenv("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL).strip() or DEFAULT_CLAUDE_MODEL
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def is_configured() -> bool:
    """Return True if the selected provider API key is present and SDK is importable."""
    provider = get_ai_provider()
    if provider == "claude":
        return bool(os.getenv("CLAUDE_API_KEY")) and Anthropic is not None
    return bool(os.getenv("GROQ_API_KEY")) and Groq is not None


def _get_client() -> "Groq | Anthropic":
    """Construct the configured AI client or raise :class:`LLMConfigError`."""
    provider = get_ai_provider()
    if provider == "claude":
        if Anthropic is None:
            raise LLMConfigError(
                "The 'anthropic' package is not installed. Run: uv add anthropic"
            )
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "CLAUDE_API_KEY is not set. Add it to your .env file or environment "
                "to enable AI features."
            )
        return Anthropic(api_key=api_key)

    if Groq is None:
        raise LLMConfigError(
            "The 'groq' package is not installed. Run: uv add groq"
        )
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMConfigError(
            "GROQ_API_KEY is not set. Add it to your .env file or environment "
            "to enable AI features."
        )
    return Groq(api_key=api_key)


def _chat_completion(messages: list[dict], temperature: float = 0.3, max_tokens: int = 700) -> str:
    """Call the configured AI provider and return the message content.

    Raises:
        LLMConfigError: if the client cannot be configured.
        RuntimeError: if the API call fails or returns an empty response.
    """
    client = _get_client()
    model = get_model_name()
    provider = get_ai_provider()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise RuntimeError(f"{provider.title()} API call failed: {exc}") from exc

    if not getattr(response, "choices", None):
        raise RuntimeError(f"{provider.title()} returned an empty response (no choices).")
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError(f"{provider.title()} returned an empty response.")
    return content


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------
def _fmt_usd(value: float) -> str:
    try:
        return f"${value:,.2f}"
    except Exception:
        return str(value)


def build_portfolio_context(
    holdings: pd.DataFrame | None,
    metrics: dict | None,
    xirr: float | None = None,
    transactions: pd.DataFrame | None = None,
    include_transactions: bool = False,
    realized_pnl: float | None = None,
) -> str:
    """Build a compact text context block describing the portfolio.

    Kept compact and numeric so the model stays grounded in real figures.
    Handles a mixed stock/option, long/short portfolio.
    """
    lines: list[str] = []

    if metrics:
        lines.append("PORTFOLIO PERFORMANCE METRICS:")
        lines.append(f"- Total cash invested (lifetime cash out): {_fmt_usd(metrics.get('total_investment', 0))}")
        lines.append(f"- Total cash received (lifetime cash in): {_fmt_usd(metrics.get('total_sells', 0))}")
        lines.append(f"- Current net position value: {_fmt_usd(metrics.get('current_value', 0))}")
        lines.append(
            f"- Total return: {_fmt_usd(metrics.get('total_return', 0))} "
            f"({metrics.get('total_return_pct', 0):.2f}%)"
        )
        if realized_pnl is not None:
            lines.append(f"- Realized P/L from closed legs: {_fmt_usd(realized_pnl)}")
        if xirr is not None:
            lines.append(
                f"- XIRR (annualized): {xirr * 100:.2f}% "
                "(may be unreliable over short, high-churn windows)"
            )
        else:
            lines.append("- XIRR: not computable from available cashflows")
        lines.append("")

    if holdings is not None and not holdings.empty:
        lines.append("CURRENT OPEN POSITIONS (FIFO cost basis, live prices):")
        for row in holdings.itertuples(index=False):
            label = getattr(row, "label", row.ticker)
            position = getattr(row, "position", "long")
            asset_type = getattr(row, "asset_type", "stock")
            priced = getattr(row, "priced", True)
            kind = f"{asset_type}/{position}"
            price_note = "" if priced else " [price unavailable, using cost basis]"
            lines.append(
                f"- {label} ({kind}): qty {row.quantity:g}, "
                f"avg cost {_fmt_usd(row.avg_cost_basis)}, "
                f"price {_fmt_usd(row.current_price)}{price_note}, "
                f"value {_fmt_usd(row.market_value)} "
                f"({row.allocation_pct:.1f}% of long exposure), "
                f"unrealized {_fmt_usd(row.unrealized_gain)} "
                f"({row.unrealized_gain_pct:+.2f}%)"
            )
        lines.append("")
        lines.append(
            "NOTE: Short positions have negative market value (a liability); their "
            "gain = premium received − current buyback cost."
        )
        lines.append("")
    else:
        lines.append("CURRENT OPEN POSITIONS: none (no open positions).")
        lines.append("")

    if include_transactions and transactions is not None and not transactions.empty:
        lines.append("TRANSACTION HISTORY (most recent 50):")
        recent = transactions.sort_values("date").tail(50)
        for row in recent.itertuples(index=False):
            d = pd.Timestamp(row.date).strftime("%Y-%m-%d")
            lines.append(
                f"- {d} {row.transaction_type} {row.quantity:g} {row.ticker} @ {_fmt_usd(row.price)}"
            )
        lines.append("")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Public generation helpers
# ---------------------------------------------------------------------------
def generate_portfolio_summary(holdings: pd.DataFrame, metrics: dict, xirr: float | None = None) -> str:
    """Generate a 2-3 sentence portfolio health summary (Tab 2).

    Mentions concentration risk if one/few stocks dominate. Grounded strictly
    in the provided holdings, allocations, unrealized P/L and total value.
    """
    context = build_portfolio_context(holdings, metrics, xirr)
    user_prompt = (
        "Write a concise 2-3 sentence assessment of this portfolio's health. "
        "Explicitly call out concentration risk if one or a few positions dominate "
        "(say which). Comment on overall unrealized gain/loss and total value. "
        "Base it ONLY on the data below. End with a one-line disclaimer.\n\n"
        f"{context}"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return _chat_completion(messages, temperature=0.3, max_tokens=300)


def generate_chat_response(
    history: list[dict],
    user_message: str,
    holdings: pd.DataFrame | None,
    metrics: dict | None,
    xirr: float | None,
    transactions: pd.DataFrame | None,
    extra_context: str | None = None,
) -> str:
    """Generate a chat response grounded in portfolio context (Tab 4).

    Args:
        history: Prior chat turns as ``[{role, content}, ...]`` (user/assistant).
        user_message: The latest user question.
        holdings, metrics, xirr, transactions: Portfolio data for grounding.
        extra_context: Optional extra text (e.g. yfinance daily move data fetched
            specifically to answer a "why is it down today" question).
    """
    context = build_portfolio_context(
        holdings, metrics, xirr, transactions, include_transactions=True
    )
    if extra_context:
        context = f"{context}\n\nADDITIONAL LIVE DATA:\n{extra_context}"

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Prepend the portfolio context as a system-level grounding message.
    messages.append(
        {
            "role": "system",
            "content": (
                "Use the following portfolio context to answer the user. Do not "
                "use any information not present here.\n\n" + context
            ),
        }
    )
    # Include recent conversation history (cap to keep prompt small).
    for turn in history[-10:]:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    return _chat_completion(messages, temperature=0.4, max_tokens=800)
