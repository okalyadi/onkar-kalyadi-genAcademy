"""Tab 1: Data Upload.

Handles CSV upload, validation, display of the cleaned DataFrame, and basic
upload statistics. Stores the cleaned transactions in session state for the
other tabs. There is intentionally no manual-entry form.
"""

from __future__ import annotations

import streamlit as st

from utils.data_processing import ValidationError, compute_upload_stats, validate_and_clean


def render() -> None:
    st.header("📤 Data Upload")
    st.write(
        "Upload your stock transaction history as a CSV. The portfolio is built "
        "entirely from this file — there is no manual entry."
    )

    with st.expander("Required CSV format", expanded=False):
        st.code(
            "ticker,date,transaction_type,quantity,price\n"
            "AAPL,2023-01-10,Buy,10,145.00\n"
            "MSFT,2023-02-15,Buy,5,250.00\n"
            "AAPL,2023-06-20,Sell,3,180.00\n"
            "NVDA,2023-09-01,Buy,4,470.00",
            language="csv",
        )
        st.caption(
            "• **ticker**: US stock symbol (e.g. AAPL)  •  **date**: any parseable date  "
            "•  **transaction_type**: Buy or Sell  •  **quantity** / **price**: positive numbers"
        )

    uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="csv_uploader")

    if uploaded is None:
        if st.session_state.get("transactions") is None:
            st.info("👆 Upload a CSV file to begin. The other tabs unlock once a valid file is loaded.")
        else:
            st.success("A portfolio is currently loaded. Upload a new file to replace it.")
        return

    # Validate & clean.
    try:
        cleaned = validate_and_clean(uploaded)
    except ValidationError as exc:
        st.error(f"❌ Validation failed: {exc}")
        st.session_state["transactions"] = None
        return
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"❌ Unexpected error while reading the file: {exc}")
        st.session_state["transactions"] = None
        return

    # Persist for other tabs and reset dependent caches.
    st.session_state["transactions"] = cleaned
    st.session_state.pop("holdings", None)
    st.session_state.pop("metrics", None)

    st.success(f"✅ Loaded and validated **{len(cleaned)}** transactions.")

    # --- Upload stats ---------------------------------------------------
    stats = compute_upload_stats(cleaned)
    c1, c2, c3 = st.columns(3)
    c1.metric("Transactions", stats["num_transactions"])
    c2.metric("Unique Tickers", stats["num_tickers"])
    date_range = f"{stats['start_date']:%Y-%m-%d} → {stats['end_date']:%Y-%m-%d}"
    c3.metric("Date Range", date_range)

    c4, c5, c6 = st.columns(3)
    c4.metric("Buy Transactions", stats["num_buys"])
    c5.metric("Sell Transactions", stats["num_sells"])
    c6.metric("Duplicate Rows", stats["num_duplicates"])

    if stats["num_duplicates"] > 0:
        st.warning(
            f"⚠️ {stats['num_duplicates']} duplicate row(s) detected. They are kept as-is "
            "and counted as separate transactions — remove them from the CSV if unintended."
        )

    # --- Cleaned data ---------------------------------------------------
    st.subheader("Cleaned Transactions")
    display_df = cleaned.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn("price", format="$%.2f"),
        },
    )
