"""CSV loading, validation and cleaning for the Stock Analyst Agent.

Two input formats are supported and **auto-detected**:

1. **Simple format** — the canonical
   ``ticker,date,transaction_type,quantity,price`` (Buy/Sell stock trades).
2. **E*TRADE / Morgan Stanley** account-activity exports (stocks + options,
   long + short), parsed by :mod:`utils.broker_import`.

Both are normalized into the same **canonical extended schema** (see
:mod:`utils.broker_import`) so the rest of the app is format-agnostic.
"""

from __future__ import annotations

from io import StringIO

import numpy as np
import pandas as pd

from utils import broker_import

# The minimal columns a "simple" CSV must provide.
REQUIRED_COLUMNS = ["ticker", "date", "transaction_type", "quantity", "price"]
VALID_TRANSACTION_TYPES = {"Buy", "Sell"}

CANONICAL_COLUMNS = [
    "date", "ticker", "asset_type", "option_type", "strike", "expiry",
    "multiplier", "effect", "transaction_type", "quantity", "price",
    "amount", "commission",
]


class ValidationError(Exception):
    """Raised when an uploaded file fails validation."""


# ---------------------------------------------------------------------------
# Raw reading helpers
# ---------------------------------------------------------------------------
def _read_text(file_or_buffer) -> str:
    """Read an uploaded file / path / buffer into a decoded text string."""
    # Streamlit UploadedFile / file-like with .read()
    if hasattr(file_or_buffer, "read"):
        try:
            file_or_buffer.seek(0)
        except Exception:
            pass
        raw = file_or_buffer.read()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
    # A path string
    if isinstance(file_or_buffer, str):
        try:
            with open(file_or_buffer, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            # Treat the string itself as CSV content.
            return file_or_buffer
    raise ValidationError("Unsupported input; expected a file upload, path, or text buffer.")


# ---------------------------------------------------------------------------
# Public unified loader
# ---------------------------------------------------------------------------
def load_transactions(file_or_buffer) -> tuple[pd.DataFrame, dict]:
    """Load, auto-detect, validate and normalize a transactions file.

    Returns:
        (canonical DataFrame, import report dict).

    Raises:
        ValidationError: with a human-readable message on any failure.
    """
    text = _read_text(file_or_buffer)
    if not text or not text.strip():
        raise ValidationError("The uploaded file is empty. Please upload a CSV with transactions.")

    if broker_import.looks_like_etrade(text):
        try:
            df, report = broker_import.parse_etrade(text)
        except Exception as exc:
            raise ValidationError(f"Failed to parse the E*TRADE export: {exc}") from exc
        if df.empty:
            raise ValidationError(
                "The E*TRADE export was recognized but contained no stock or option "
                "trades (only cash/transfer activity)."
            )
        return df, report

    # Fall back to the simple canonical format.
    df = _parse_simple(text)
    report = {
        "format": "Simple CSV",
        "total_activity_rows": int(len(df)),
        "kept": int(len(df)),
        "stocks": int((df["asset_type"] == "stock").sum()),
        "options": int((df["asset_type"] == "option").sum()),
        "skipped_cash": 0,
        "skipped_other": 0,
        "warnings": [],
    }
    return df, report


# ---------------------------------------------------------------------------
# Simple-format parsing & validation
# ---------------------------------------------------------------------------
def _parse_simple(text: str) -> pd.DataFrame:
    """Validate and normalize the simple ``ticker,date,...`` format."""
    try:
        df = pd.read_csv(StringIO(text))
    except pd.errors.EmptyDataError as exc:
        raise ValidationError("The uploaded CSV is empty.") from exc
    except Exception as exc:
        raise ValidationError(f"Could not read the CSV file: {exc}") from exc

    if df is None or df.empty:
        raise ValidationError("The uploaded CSV has no rows. Please add at least one transaction.")

    # Column presence (case-insensitive header match).
    normalized = {str(c).strip().lower(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c not in normalized]
    if missing:
        raise ValidationError(
            "This does not look like an E*TRADE export, and the simple format is "
            "missing required column(s): "
            + ", ".join(missing)
            + ". Expected headers: "
            + ", ".join(REQUIRED_COLUMNS)
            + "."
        )
    df = df.rename(columns={normalized[c]: c for c in REQUIRED_COLUMNS})[REQUIRED_COLUMNS].copy()

    # ticker
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    if (df["ticker"] == "").any() or df["ticker"].isin(["NAN", "NONE"]).any():
        raise ValidationError("One or more rows have a missing/blank ticker symbol.")

    # transaction_type
    tx = df["transaction_type"].astype(str).str.strip().str.lower()
    mapping = {"buy": "Buy", "sell": "Sell"}
    invalid = tx[~tx.isin(mapping)]
    if not invalid.empty:
        bad = sorted(set(invalid.tolist()))
        raise ValidationError(
            "transaction_type must be 'Buy' or 'Sell' (case-insensitive). "
            f"Found invalid value(s): {', '.join(bad)}."
        )
    df["transaction_type"] = tx.map(mapping)

    # date
    parsed = pd.to_datetime(df["date"], errors="coerce")
    if parsed.isna().any():
        bad_rows = parsed.isna().to_numpy().nonzero()[0]
        line_numbers = [int(i) + 2 for i in bad_rows]
        raise ValidationError(
            "Some dates could not be parsed. Check CSV line(s): "
            + ", ".join(map(str, line_numbers))
            + "."
        )
    df["date"] = parsed

    # quantity / price
    qty = pd.to_numeric(df["quantity"], errors="coerce")
    if qty.isna().any():
        raise ValidationError("Column 'quantity' contains non-numeric values.")
    if (qty <= 0).any():
        raise ValidationError("Column 'quantity' must contain positive (> 0) values.")
    price = pd.to_numeric(df["price"], errors="coerce")
    if price.isna().any():
        raise ValidationError("Column 'price' contains non-numeric values.")
    if (price <= 0).any():
        raise ValidationError("Column 'price' must contain positive (> 0) values.")

    # Build canonical records.
    records = []
    for row in df.itertuples(index=False):
        effect = "open_long" if row.transaction_type == "Buy" else "close_long"
        gross = float(row.price) * float(row.quantity)
        amount = -gross if effect == "open_long" else gross
        records.append(
            {
                "date": row.date,
                "ticker": row.ticker,
                "asset_type": "stock",
                "option_type": "",
                "strike": float("nan"),
                "expiry": pd.NaT,
                "multiplier": 1.0,
                "effect": effect,
                "transaction_type": row.transaction_type,
                "quantity": float(row.quantity),
                "price": float(row.price),
                "amount": amount,
                "commission": 0.0,
            }
        )
    return broker_import.build_canonical_frame(records)


# Backwards-compatible helper: validate a simple CSV buffer -> canonical df.
def validate_and_clean(file_or_buffer) -> pd.DataFrame:
    """Validate a *simple-format* CSV and return the canonical DataFrame.

    Kept for backward compatibility / direct simple-format use. For
    auto-detecting uploads, prefer :func:`load_transactions`.
    """
    return _parse_simple(_read_text(file_or_buffer))


# ---------------------------------------------------------------------------
# Upload statistics
# ---------------------------------------------------------------------------
def compute_upload_stats(df: pd.DataFrame) -> dict:
    """Return basic summary stats about a canonical transaction DataFrame."""
    buys = int((df["transaction_type"] == "Buy").sum())
    sells = int((df["transaction_type"] == "Sell").sum())
    return {
        "num_transactions": int(len(df)),
        "num_tickers": int(df["ticker"].nunique()),
        "start_date": df["date"].min(),
        "end_date": df["date"].max(),
        "num_buys": buys,
        "num_sells": sells,
        "num_stocks": int((df["asset_type"] == "stock").sum()),
        "num_options": int((df["asset_type"] == "option").sum()),
        "num_duplicates": int(df.duplicated().sum()),
    }
