"""Broker statement importers.

Currently supports auto-detecting and parsing **E*TRADE / Morgan Stanley**
"Account Activity" CSV exports, which look nothing like the app's simple
``ticker,date,transaction_type,quantity,price`` format. Such exports contain:

    * a multi-line preamble (title lines + ``Total:`` row) before the header,
    * a legal footer of quoted paragraphs after the data,
    * three kinds of rows: equity (stock) trades, option trades, and
      non-trade cash activity (transfers, interest, margin interest).

The parser normalizes trades (stocks + options, long + short) into the
**canonical extended schema** used throughout the app and returns a structured
import report describing what was kept and skipped.

Canonical extended schema (one row per trade):

    date           datetime64    trade date
    ticker         str           underlying symbol (yfinance ticker)
    asset_type     str           "stock" | "option"
    option_type    str           "call" | "put" | ""  (empty for stocks)
    strike         float         option strike       (NaN for stocks)
    expiry         datetime64    option expiry        (NaT for stocks)
    multiplier     float         100 for options, 1 for stocks
    effect         str           open_long | close_long | open_short | close_short
    transaction_type str         "Buy" | "Sell" (display-friendly cash direction)
    quantity       float         shares / contracts (positive)
    price          float         per-share / per-contract-share price (positive)
    amount         float         signed cash impact (− = cash out, + = cash in)
    commission     float         commission paid
"""

from __future__ import annotations

import re
from io import StringIO

import numpy as np
import pandas as pd

# E*TRADE Activity Type -> (asset_type, effect)
_ACTIVITY_MAP = {
    # Equities (whole-share trades use plain Bought/Sold).
    "bought": ("stock", "open_long"),
    "sold": ("stock", "close_long"),
    # Options (always use the To Open/Close/Cover or Short variants).
    "bought to open": ("option", "open_long"),
    "sold to close": ("option", "close_long"),
    "sold to open": ("option", "open_short"),
    "sold short": ("option", "open_short"),
    "bought to cover": ("option", "close_short"),
    "bought to close": ("option", "close_short"),
}

# Non-trade activity that funds the account but is not investment performance.
_NON_TRADE_ACTIVITY = {
    "online transfer",
    "transfer",
    "margin interest",
    "interest income",
    "dividend",
    "fee",
}

# "CALL QQQ    06/05/26   727.000"  /  "PUT  SPXW   05/26/26  7510.000"
_OPTION_DESC_RE = re.compile(
    r"^\s*(CALL|PUT)\s+(\S+)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+([\d.]+)\s*$",
    re.IGNORECASE,
)


def looks_like_etrade(text: str) -> bool:
    """Heuristically detect an E*TRADE / Morgan Stanley activity export."""
    head = text[:4000].lower()
    has_header = "activity type" in head and "symbol" in head
    has_marker = (
        "e*trade" in head
        or "morgan stanley" in head
        or "account activity" in head
        or "bought to open" in head
        or "sold to close" in head
    )
    return has_header and has_marker


def _find_header_index(lines: list[str]) -> int | None:
    """Return the index of the real CSV header line, or None."""
    for i, line in enumerate(lines):
        low = line.lower()
        if "activity type" in low and "symbol" in low and "quantity" in low:
            return i
    return None


def _parse_money(value) -> float:
    """Parse a possibly-messy money/number cell into a float (NaN if blank)."""
    if value is None:
        return float("nan")
    s = str(value).strip().replace("$", "").replace(",", "")
    if s in {"", "--", "nan", "none"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _parse_date(value) -> pd.Timestamp:
    """Parse an E*TRADE MM/DD/YY date."""
    return pd.to_datetime(str(value).strip(), errors="coerce")


def _parse_option_description(desc: str):
    """Parse an option description into (option_type, underlying, expiry, strike).

    Returns None if the description is not a recognizable option.
    """
    m = _OPTION_DESC_RE.match(desc or "")
    if not m:
        return None
    opt_type = m.group(1).lower()
    underlying = m.group(2).upper()
    expiry = pd.to_datetime(m.group(3), errors="coerce")
    try:
        strike = float(m.group(4))
    except ValueError:
        strike = float("nan")
    return opt_type, underlying, expiry, strike


def parse_etrade(text: str) -> tuple[pd.DataFrame, dict]:
    """Parse an E*TRADE activity export into the canonical extended schema.

    Returns:
        (DataFrame, report). The report dict summarizes detection and what was
        kept vs. skipped, plus any per-row warnings.
    """
    lines = text.splitlines()
    hdr_idx = _find_header_index(lines)
    if hdr_idx is None:
        raise ValueError("Could not locate the E*TRADE data header row.")

    raw = pd.read_csv(StringIO("\n".join(lines[hdr_idx:])))
    raw.columns = [str(c).strip() for c in raw.columns]

    # Be tolerant of slight header naming differences.
    def col(*candidates: str) -> str | None:
        lowered = {c.lower(): c for c in raw.columns}
        for cand in candidates:
            if cand.lower() in lowered:
                return lowered[cand.lower()]
        return None

    c_activity = col("Activity Type")
    c_desc = col("Description")
    c_symbol = col("Symbol")
    c_qty = col("Quantity #", "Quantity")
    c_price = col("Price $", "Price")
    c_amount = col("Amount $", "Amount")
    c_comm = col("Commission")
    c_date = col("Activity/Trade Date", "Trade Date", "Activity Date", "Date")

    if not all([c_activity, c_symbol, c_qty, c_price, c_date]):
        raise ValueError("E*TRADE export is missing one or more required columns.")

    records: list[dict] = []
    warnings: list[str] = []
    skipped_cash = 0
    skipped_other = 0
    n_stock = 0
    n_option = 0

    total_rows = 0
    for r in raw.itertuples(index=False):
        row = dict(zip(raw.columns, r))
        activity_raw = row.get(c_activity)
        if activity_raw is None or (isinstance(activity_raw, float) and pd.isna(activity_raw)):
            continue  # footer paragraph / blank row
        activity = str(activity_raw).strip().lower()
        if not activity or activity == "nan":
            continue
        total_rows += 1

        if activity in _NON_TRADE_ACTIVITY:
            skipped_cash += 1
            continue
        if activity not in _ACTIVITY_MAP:
            skipped_other += 1
            warnings.append(f"Skipped unrecognized activity type: '{activity_raw}'.")
            continue

        asset_type, effect = _ACTIVITY_MAP[activity]

        date = _parse_date(row.get(c_date))
        if pd.isna(date):
            skipped_other += 1
            warnings.append(f"Skipped a '{activity_raw}' row with an unparseable date.")
            continue

        qty = abs(_parse_money(row.get(c_qty)))
        price = abs(_parse_money(row.get(c_price)))
        amount = _parse_money(row.get(c_amount)) if c_amount else float("nan")
        commission = _parse_money(row.get(c_comm)) if c_comm else 0.0
        if not np.isfinite(commission):
            commission = 0.0

        symbol = str(row.get(c_symbol) or "").strip().upper()
        desc = str(row.get(c_desc) or "").strip()

        option_type = ""
        strike = float("nan")
        expiry = pd.NaT

        if asset_type == "option":
            parsed = _parse_option_description(desc)
            if parsed is None:
                skipped_other += 1
                warnings.append(f"Skipped an option row with unparseable description: '{desc}'.")
                continue
            option_type, underlying, expiry, strike = parsed
            multiplier = 100.0
            # Prefer the account Symbol column for the yfinance ticker; fall back
            # to the underlying parsed from the description.
            ticker = symbol or underlying
            n_option += 1
        else:
            multiplier = 1.0
            ticker = symbol
            if not ticker:
                skipped_other += 1
                warnings.append("Skipped a stock row with no symbol.")
                continue
            n_stock += 1

        if not np.isfinite(qty) or qty <= 0 or not np.isfinite(price) or price <= 0:
            skipped_other += 1
            warnings.append(f"Skipped a '{activity_raw}' {ticker} row with invalid quantity/price.")
            continue

        # If the broker didn't give an amount, derive a signed one.
        if not np.isfinite(amount):
            gross = price * qty * multiplier
            amount = -gross if effect in {"open_long", "close_short"} else gross

        transaction_type = "Buy" if effect in {"open_long", "close_short"} else "Sell"

        records.append(
            {
                "date": date,
                "ticker": ticker,
                "asset_type": asset_type,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "multiplier": multiplier,
                "effect": effect,
                "transaction_type": transaction_type,
                "quantity": qty,
                "price": price,
                "amount": amount,
                "commission": commission,
            }
        )

    # E*TRADE exports are newest-first (reverse chronological), including the
    # order of multiple trades on the same day. Reverse so that, after the
    # stable date-sort in build_canonical_frame, same-day trades are processed
    # oldest-first (otherwise a same-day buy+sell would be seen sell-then-buy).
    records.reverse()
    df = build_canonical_frame(records)

    report = {
        "format": "E*TRADE / Morgan Stanley",
        "total_activity_rows": total_rows,
        "kept": len(records),
        "stocks": n_stock,
        "options": n_option,
        "skipped_cash": skipped_cash,
        "skipped_other": skipped_other,
        "warnings": warnings,
    }
    return df, report


def build_canonical_frame(records: list[dict]) -> pd.DataFrame:
    """Build a canonical extended DataFrame (typed, date-sorted) from records."""
    columns = [
        "date", "ticker", "asset_type", "option_type", "strike", "expiry",
        "multiplier", "effect", "transaction_type", "quantity", "price",
        "amount", "commission",
    ]
    if not records:
        empty = pd.DataFrame(columns=columns)
        empty["date"] = pd.to_datetime(empty["date"])
        empty["expiry"] = pd.to_datetime(empty["expiry"])
        return empty

    df = pd.DataFrame.from_records(records, columns=columns)
    df["date"] = pd.to_datetime(df["date"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    for c in ["strike", "multiplier", "quantity", "price", "amount", "commission"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Stable chronological sort so FIFO is deterministic.
    df = df.sort_values("date", kind="stable").reset_index(drop=True)
    return df
