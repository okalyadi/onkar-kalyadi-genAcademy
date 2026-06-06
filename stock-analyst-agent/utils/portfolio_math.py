"""Portfolio financial calculations for the Stock Analyst Agent.

Handles a mixed portfolio of **stocks and options**, **long and short**:

    * Long/short FIFO position & cost-basis calculation per instrument.
    * Realized P/L from closed legs (with the option ×100 multiplier).
    * Cashflow-based lifetime metrics (works when shorts/options make the naive
      "sells − buys" formula invalid).
    * XIRR over the full trade-cashflow timeline + current net liquidation value.
    * yfinance pricing: live stock quotes and best-effort option-chain pricing.

Instruments are keyed by ``(ticker, asset_type, option_type, strike, expiry)``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

try:  # Streamlit is optional at import time (e.g. for unit tests).
    import streamlit as st

    _cache_data = st.cache_data
except Exception:  # pragma: no cover - fallback when Streamlit unavailable
    def _cache_data(*dargs, **dkwargs):
        def _decorator(func):
            return func

        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        return _decorator


class PortfolioError(Exception):
    """Raised when transactions are irrecoverably inconsistent."""


# ---------------------------------------------------------------------------
# Instrument helpers
# ---------------------------------------------------------------------------
def _instrument_key(row) -> tuple:
    # Use None (not NaN) for absent strike/expiry: NaN != NaN would put every
    # stock buy and its matching sell into separate books, breaking FIFO.
    expiry = row.expiry
    expiry_iso = "" if pd.isna(expiry) else pd.Timestamp(expiry).strftime("%Y-%m-%d")
    strike = float(row.strike) if pd.notna(row.strike) else None
    return (row.ticker, row.asset_type, row.option_type or "", strike, expiry_iso)


def instrument_label(asset_type, ticker, option_type, strike, expiry) -> str:
    """Human-readable instrument label, e.g. ``QQQ 07/10/26 730C``."""
    if asset_type != "option":
        return str(ticker)
    exp = "" if pd.isna(expiry) else pd.Timestamp(expiry).strftime("%m/%d/%y")
    cp = "C" if str(option_type).lower().startswith("c") else "P"
    strike_str = f"{float(strike):g}" if pd.notna(strike) else "?"
    return f"{ticker} {exp} {strike_str}{cp}".strip()


# ---------------------------------------------------------------------------
# Long/short FIFO positions
# ---------------------------------------------------------------------------
def compute_positions(df: pd.DataFrame) -> tuple[pd.DataFrame, float, list[str]]:
    """Compute open long/short positions via FIFO, plus realized P/L.

    Args:
        df: Canonical extended transaction DataFrame (date-sorted).

    Returns:
        (positions DataFrame, total_realized_pnl, warnings).

    Positions columns:
        ``key, ticker, asset_type, option_type, strike, expiry, multiplier,
        position (long/short), quantity, avg_cost_basis, cost_basis_total``.

    Closing more than is held in-window (common with broker exports limited to a
    recent window) is treated as a pre-existing position with unknown cost
    basis: the matched part is realized, the remainder is warned about and
    ignored (never flips into an unintended short).
    """
    df = df.sort_values("date", kind="stable")
    books: dict[tuple, dict] = defaultdict(
        lambda: {"long": deque(), "short": deque(), "meta": None}
    )
    realized = 0.0
    warnings: list[str] = []

    for row in df.itertuples(index=False):
        key = _instrument_key(row)
        book = books[key]
        if book["meta"] is None:
            book["meta"] = {
                "ticker": row.ticker,
                "asset_type": row.asset_type,
                "option_type": row.option_type or "",
                "strike": float(row.strike) if pd.notna(row.strike) else float("nan"),
                "expiry": row.expiry,
                "multiplier": float(row.multiplier),
            }
        qty = float(row.quantity)
        price = float(row.price)
        mult = float(row.multiplier)
        label = instrument_label(
            row.asset_type, row.ticker, row.option_type, row.strike, row.expiry
        )

        if row.effect == "open_long":
            book["long"].append([qty, price])
        elif row.effect == "open_short":
            book["short"].append([qty, price])
        elif row.effect == "close_long":
            remaining = qty
            while remaining > 1e-9 and book["long"]:
                lot = book["long"][0]
                take = min(lot[0], remaining)
                realized += (price - lot[1]) * mult * take
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-9:
                    book["long"].popleft()
            if remaining > 1e-9:
                warnings.append(
                    f"{label}: closed {remaining:g} more than held in this file "
                    "(treated as a pre-window position with unknown cost basis)."
                )
        elif row.effect == "close_short":
            remaining = qty
            while remaining > 1e-9 and book["short"]:
                lot = book["short"][0]
                take = min(lot[0], remaining)
                realized += (lot[1] - price) * mult * take
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-9:
                    book["short"].popleft()
            if remaining > 1e-9:
                warnings.append(
                    f"{label}: covered {remaining:g} more than was open in this file "
                    "(treated as a pre-window short with unknown premium)."
                )

    rows = []
    for key, book in books.items():
        meta = book["meta"]
        for side, lots in (("long", book["long"]), ("short", book["short"])):
            q = sum(l[0] for l in lots)
            if q <= 1e-9:
                continue
            cost_total = sum(l[0] * l[1] for l in lots)  # per-share basis (× mult later for $)
            rows.append(
                {
                    "key": key,
                    "ticker": meta["ticker"],
                    "asset_type": meta["asset_type"],
                    "option_type": meta["option_type"],
                    "strike": meta["strike"],
                    "expiry": meta["expiry"],
                    "multiplier": meta["multiplier"],
                    "position": side,
                    "quantity": round(q, 6),
                    "avg_cost_basis": cost_total / q if q else 0.0,
                    "cost_basis_total": cost_total * meta["multiplier"],
                }
            )

    positions = pd.DataFrame(
        rows,
        columns=[
            "key", "ticker", "asset_type", "option_type", "strike", "expiry",
            "multiplier", "position", "quantity", "avg_cost_basis", "cost_basis_total",
        ],
    )
    return positions, realized, warnings


# ---------------------------------------------------------------------------
# yfinance: stock quotes
# ---------------------------------------------------------------------------
@_cache_data(ttl=900, show_spinner=False)
def fetch_quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Fetch current price, previous close and daily move for stock tickers."""
    result: dict[str, dict] = {}
    for ticker in tickers:
        info = {
            "current_price": float("nan"),
            "previous_close": float("nan"),
            "day_change": float("nan"),
            "day_change_pct": float("nan"),
            "ok": False,
        }
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
            closes = hist["Close"].dropna() if hist is not None and not hist.empty else None
            if closes is not None and len(closes) >= 1:
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) >= 2 else current
                info.update(
                    current_price=current,
                    previous_close=prev,
                    day_change=current - prev,
                    day_change_pct=((current - prev) / prev * 100.0) if prev else float("nan"),
                    ok=True,
                )
        except Exception:
            pass
        result[ticker] = info
    return result


# ---------------------------------------------------------------------------
# yfinance: option-chain pricing (best effort)
# ---------------------------------------------------------------------------
@_cache_data(ttl=900, show_spinner=False)
def fetch_option_prices(contracts: tuple[tuple, ...]) -> dict[tuple, dict]:
    """Best-effort current pricing for option contracts via yfinance chains.

    Args:
        contracts: tuple of ``(ticker, expiry_iso, option_type, strike)``.

    Returns dict keyed by the same contract tuple ->
        ``{"price": float, "ok": bool}``.

    Contracts whose expiry is not currently listed on yfinance (e.g. already
    expired weeklies) are returned with ``ok=False``.
    """
    result: dict[tuple, dict] = {c: {"price": float("nan"), "ok": False} for c in contracts}

    # Group by (ticker, expiry) to minimize network calls.
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for c in contracts:
        ticker, expiry_iso, _opt, _strike = c
        groups[(ticker, expiry_iso)].append(c)

    for (ticker, expiry_iso), members in groups.items():
        if not expiry_iso:
            continue
        try:
            tk = yf.Ticker(ticker)
            available = set(tk.options or ())
            if expiry_iso not in available:
                continue
            chain = tk.option_chain(expiry_iso)
            for c in members:
                _t, _e, opt_type, strike = c
                table = chain.calls if str(opt_type).lower().startswith("c") else chain.puts
                if table is None or table.empty:
                    continue
                match = table.loc[(table["strike"] - float(strike)).abs() < 1e-6]
                if match.empty:
                    continue
                rec = match.iloc[0]
                price = rec.get("lastPrice")
                bid, ask = rec.get("bid"), rec.get("ask")
                # Prefer a bid/ask midpoint when both are present and positive.
                if bid and ask and bid > 0 and ask > 0:
                    price = (float(bid) + float(ask)) / 2.0
                if price is not None and np.isfinite(price) and price >= 0:
                    result[c] = {"price": float(price), "ok": True}
        except Exception:
            continue

    return result


# ---------------------------------------------------------------------------
# Enriched current holdings (positions + live valuation)
# ---------------------------------------------------------------------------
def build_current_holdings(
    df: pd.DataFrame, price_options: bool = True
) -> tuple[pd.DataFrame, dict]:
    """Build the enriched current-holdings table with live valuation.

    Returns:
        (holdings DataFrame, info dict). The info dict contains
        ``realized_pnl``, ``warnings``, ``unpriced`` (list of labels that could
        not be priced) and ``stock_failures`` (stock tickers with no quote).

    Holdings columns add to the positions columns:
        ``label, current_price, market_value, unrealized_gain,
        unrealized_gain_pct, allocation_pct, priced, day_change, day_change_pct``.
    """
    positions, realized, warnings = compute_positions(df)

    info = {
        "realized_pnl": realized,
        "warnings": warnings,
        "unpriced": [],
        "stock_failures": [],
    }

    extra_cols = [
        "label", "current_price", "market_value", "unrealized_gain",
        "unrealized_gain_pct", "allocation_pct", "priced", "day_change", "day_change_pct",
    ]
    if positions.empty:
        for c in extra_cols:
            positions[c] = pd.Series(dtype="float64")
        return positions, info

    # --- Gather prices --------------------------------------------------
    stock_tickers = tuple(
        sorted(positions.loc[positions["asset_type"] == "stock", "ticker"].unique())
    )
    quotes = fetch_quotes(stock_tickers) if stock_tickers else {}

    option_rows = positions[positions["asset_type"] == "option"]
    option_contracts = tuple(
        (
            r.ticker,
            "" if pd.isna(r.expiry) else pd.Timestamp(r.expiry).strftime("%Y-%m-%d"),
            r.option_type,
            float(r.strike) if pd.notna(r.strike) else float("nan"),
        )
        for r in option_rows.itertuples(index=False)
    )
    option_prices = (
        fetch_option_prices(option_contracts)
        if (price_options and option_contracts)
        else {}
    )

    labels, prices, mvs = [], [], []
    gains, gain_pcts, priced_flags = [], [], []
    day_changes, day_change_pcts = [], []

    for r in positions.itertuples(index=False):
        label = instrument_label(r.asset_type, r.ticker, r.option_type, r.strike, r.expiry)
        labels.append(label)
        mult = r.multiplier
        priced = False
        price = float("nan")
        day_change = float("nan")
        day_change_pct = float("nan")

        if r.asset_type == "stock":
            q = quotes.get(r.ticker, {})
            if q.get("ok"):
                price = q["current_price"]
                day_change = q.get("day_change", float("nan"))
                day_change_pct = q.get("day_change_pct", float("nan"))
                priced = True
            else:
                info["stock_failures"].append(r.ticker)
        else:
            ckey = (
                r.ticker,
                "" if pd.isna(r.expiry) else pd.Timestamp(r.expiry).strftime("%Y-%m-%d"),
                r.option_type,
                float(r.strike) if pd.notna(r.strike) else float("nan"),
            )
            op = option_prices.get(ckey, {})
            if op.get("ok"):
                price = op["price"]
                priced = True
            else:
                info["unpriced"].append(label)

        if not priced or pd.isna(price):
            price = r.avg_cost_basis  # fall back so the row still renders

        gross_mv = price * r.quantity * mult
        cost_total = r.cost_basis_total  # already × multiplier
        if r.position == "long":
            market_value = gross_mv
            gain = market_value - cost_total
        else:  # short: market value is a liability; gain = premium − buyback cost
            market_value = -gross_mv
            gain = cost_total - gross_mv
        gain_pct = (gain / cost_total * 100.0) if cost_total else 0.0

        prices.append(price)
        mvs.append(market_value)
        gains.append(gain)
        gain_pcts.append(gain_pct)
        priced_flags.append(priced)
        day_changes.append(day_change)
        day_change_pcts.append(day_change_pct)

    positions["label"] = labels
    positions["current_price"] = prices
    positions["market_value"] = mvs
    positions["unrealized_gain"] = gains
    positions["unrealized_gain_pct"] = gain_pcts
    positions["priced"] = priced_flags
    positions["day_change"] = day_changes
    positions["day_change_pct"] = day_change_pcts

    total_long_mv = positions.loc[positions["market_value"] > 0, "market_value"].sum()
    positions["allocation_pct"] = np.where(
        positions["market_value"] > 0,
        positions["market_value"] / total_long_mv * 100.0 if total_long_mv else 0.0,
        0.0,
    )

    positions = positions.sort_values("market_value", ascending=False).reset_index(drop=True)
    info["stock_failures"] = sorted(set(info["stock_failures"]))
    return positions, info


# ---------------------------------------------------------------------------
# Lifetime performance metrics (cashflow-based)
# ---------------------------------------------------------------------------
def compute_performance_metrics(df: pd.DataFrame, holdings: pd.DataFrame) -> dict:
    """Compute lifetime performance metrics from signed trade cashflows.

    Works for mixed stock/option, long/short portfolios:
        total_investment = total cash out (buys / BTO / BTC)
        total_sells      = total cash in  (sells / STC / STO premium)
        current_value    = net liquidation value of open positions
        total_return     = total_sells + current_value − total_investment
    """
    amounts = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    cash_in = float(amounts[amounts > 0].sum())
    cash_out = float(-amounts[amounts < 0].sum())
    current_value = float(holdings["market_value"].sum()) if not holdings.empty else 0.0

    total_return = cash_in + current_value - cash_out
    total_return_pct = (total_return / cash_out * 100.0) if cash_out else 0.0

    return {
        "total_investment": cash_out,
        "total_sells": cash_in,
        "current_value": current_value,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "net_invested": cash_out - cash_in,
    }


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------
def _xnpv(rate: float, cashflows: list[tuple[datetime, float]]) -> float:
    t0 = cashflows[0][0]
    return sum(cf / (1.0 + rate) ** ((dt - t0).days / 365.0) for dt, cf in cashflows)


def _xnpv_derivative(rate: float, cashflows: list[tuple[datetime, float]]) -> float:
    t0 = cashflows[0][0]
    total = 0.0
    for dt, cf in cashflows:
        years = (dt - t0).days / 365.0
        total -= years * cf / (1.0 + rate) ** (years + 1.0)
    return total


def compute_xirr(df: pd.DataFrame, current_value: float, as_of: datetime | None = None) -> float | None:
    """Compute portfolio XIRR from signed trade cashflows + current value.

    Uses the canonical ``amount`` column (already signed: − cash out, + cash in)
    plus the current net liquidation value as a final cashflow today. Returns
    the annualized rate as a decimal, or ``None`` if not computable.
    """
    if df.empty:
        return None
    as_of = as_of or datetime.now()

    cashflows: list[tuple[datetime, float]] = []
    for row in df.itertuples(index=False):
        amt = float(row.amount) if pd.notna(row.amount) else 0.0
        if amt == 0.0:
            continue
        cashflows.append((pd.Timestamp(row.date).to_pydatetime(), amt))

    if current_value != 0:
        cashflows.append((as_of, float(current_value)))

    cashflows.sort(key=lambda x: x[0])
    if len(cashflows) < 2:
        return None
    amounts = [cf for _, cf in cashflows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        return None
    if cashflows[0][0] == cashflows[-1][0]:
        return None

    # Attempt 1: scipy brentq over a bracketed sign change.
    try:
        from scipy.optimize import brentq

        f = lambda r: _xnpv(r, cashflows)
        grid = np.linspace(-0.9999, 10.0, 200)
        prev_r, prev_v = grid[0], f(grid[0])
        for r in grid[1:]:
            v = f(r)
            if np.isfinite(prev_v) and np.isfinite(v) and prev_v * v < 0:
                return float(brentq(f, prev_r, r, maxiter=200))
            prev_r, prev_v = r, v
    except Exception:
        pass

    # Attempt 2: guarded Newton's method.
    rate = 0.1
    for _ in range(100):
        try:
            value = _xnpv(rate, cashflows)
            deriv = _xnpv_derivative(rate, cashflows)
            if deriv == 0 or not np.isfinite(deriv):
                break
            new_rate = rate - value / deriv
            if new_rate <= -0.9999:
                new_rate = (rate - 0.9999) / 2.0
            if abs(new_rate - rate) < 1e-7:
                return float(new_rate)
            rate = new_rate
        except (OverflowError, ZeroDivisionError, FloatingPointError):
            break
    return None


# ---------------------------------------------------------------------------
# Cumulative cashflow series (optional chart)
# ---------------------------------------------------------------------------
def cumulative_cashflow_series(df: pd.DataFrame) -> pd.DataFrame:
    """Return a date-indexed cumulative *net invested* series (cumsum of −amount)."""
    tmp = df.copy()
    tmp["net_invested_flow"] = -pd.to_numeric(tmp["amount"], errors="coerce").fillna(0.0)
    grouped = tmp.groupby("date", as_index=False)["net_invested_flow"].sum().sort_values("date")
    grouped["cumulative_net_invested"] = grouped["net_invested_flow"].cumsum()
    return grouped[["date", "cumulative_net_invested"]]
