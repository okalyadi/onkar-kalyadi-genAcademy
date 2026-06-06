# 📈 Stock Analyst Agent

An AI-powered **US Stock Portfolio Analyst** built with Streamlit. Upload your
transaction history as a CSV and the app builds your consolidated portfolio,
computes performance (FIFO cost basis + XIRR), visualizes allocation and
returns, and lets you chat with an AI analyst powered by **Groq** — all grounded
strictly in your data and live prices from **yfinance**.

> ⚠️ **Disclaimer:** This project is for **educational and informational use
> only**. It does **not** constitute financial advice. Prices from yfinance may
> be delayed or inaccurate.

---

## Features

- **CSV-only portfolio** — no manual entry; everything is derived from your
  uploaded transaction history.
- **Strict validation** — required columns, Buy/Sell-only types, positive
  numeric quantity/price, parseable dates, ticker normalization.
- **FIFO cost basis** — current holdings, average cost, and remaining cost basis
  computed lot-by-lot (oldest buys consumed first).
- **Live prices** via yfinance (cached for 15 minutes).
- **Consolidated view** — allocation pie chart, total value, per-stock
  unrealized P/L table, and an AI portfolio-health summary.
- **Historical performance** — total invested, total sells, current value, total
  return, and **XIRR** over the full cashflow timeline, plus a cumulative
  capital-deployed chart and full transaction table.
- **AI analyst chat** — grounded Q&A over your portfolio; fetches recent price
  moves from yfinance when you ask about "today".

---

## Folder Structure

```
stock-analyst-agent/
│
├── app.py                      # Streamlit entry point, page config, tabs
│
├── pyproject.toml              # uv-managed dependencies
├── uv.lock                     # generated lockfile (created by uv)
├── README.md
├── .env.example
├── .gitignore
│
├── utils/
│   ├── __init__.py
│   ├── data_processing.py      # CSV validation & cleaning
│   ├── portfolio_math.py       # FIFO, XIRR, metrics, yfinance prices
│   └── llm_agent.py            # Groq client wrapper & prompts
│
└── components/
    ├── __init__.py
    ├── data_upload_tab.py      # Tab 1
    ├── portfolio_view_tab.py   # Tab 2
    ├── historical_performance_tab.py  # Tab 3
    └── ai_chat_tab.py          # Tab 4
```

---

## CSV Format

The app accepts **only** a CSV with these exact headers:

```
ticker,date,transaction_type,quantity,price
```

| Column            | Description                                             |
| ----------------- | ------------------------------------------------------- |
| `ticker`          | US stock ticker (e.g. `AAPL`, `MSFT`, `NVDA`)           |
| `date`            | Transaction date (any parseable format, e.g. ISO)       |
| `transaction_type`| `Buy` or `Sell` (case-insensitive)                      |
| `quantity`        | Number of shares (> 0)                                  |
| `price`           | Transaction price per share in USD (> 0)                |

### Sample CSV

```csv
ticker,date,transaction_type,quantity,price
AAPL,2023-01-10,Buy,10,145.00
MSFT,2023-02-15,Buy,5,250.00
AAPL,2023-06-20,Sell,3,180.00
NVDA,2023-09-01,Buy,4,470.00
```

---

## Setup (uv only)

This project uses [**uv**](https://docs.astral.sh/uv/) exclusively. Do **not**
use pip, venv, conda, poetry, or requirements.txt.

```bash
# 1. (If starting from scratch) initialize — already done in this repo
uv init

# 2. Add dependencies (already declared in pyproject.toml; this (re)creates uv.lock)
uv add streamlit pandas numpy yfinance plotly groq python-dotenv scipy

# 3. Run the app
uv run streamlit run app.py
```

`uv` will automatically create the virtual environment and install everything
from `pyproject.toml` / `uv.lock` on first run.

---

## Environment Variables

Copy the example file and add your Groq API key:

```bash
cp .env.example .env
```

`.env`:

```
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.1-8b-instant
```

- `GROQ_API_KEY` — required for the AI summary and chat. Get one at
  <https://console.groq.com>. If missing, the app still runs; AI features show a
  friendly warning instead of crashing.
- `GROQ_MODEL` — optional; defaults to `llama-3.1-8b-instant`. Use any model
  available on your Groq account.

Variables are loaded locally via `python-dotenv`. **No keys are hard-coded.**

---

## How to Run

```bash
uv run streamlit run app.py
```

Then open the URL Streamlit prints (usually <http://localhost:8501>), go to the
**Data Upload** tab, and upload a CSV. The other tabs unlock once a valid file
is loaded.

---

## Notes on FIFO Cost Basis

Holdings are computed using **First-In-First-Out**:

- Each **Buy** adds a lot `(quantity, price)`.
- Each **Sell** consumes the **oldest open lots first**.
- Remaining lots define current quantity and remaining cost basis.
- **Average cost basis** = remaining cost basis ÷ current quantity.
- Fully-sold positions disappear from current holdings.
- Selling more shares than are held at that point raises a clear error.

---

## Notes on XIRR

XIRR (annualized, money-weighted return) is computed over the **full cashflow
timeline**:

- **Buys** → negative cashflows (cash out).
- **Sells** → positive cashflows (cash in).
- **Current portfolio value** → final positive cashflow dated *today*.

The solver first tries `scipy.optimize.brentq` over a bracketed sign change, and
falls back to a guarded Newton's method. If a rate cannot be found (e.g. all
cashflows share one sign or a single date), the app shows `N/A` gracefully
instead of crashing.

---

## Edge Cases Handled

Empty CSV · missing columns · invalid dates · invalid transaction types ·
non-positive quantity/price · sell-before-buy · overselling · fully-sold
positions · failed yfinance fetch · missing Groq key · non-computable XIRR ·
duplicate rows · mixed-case tickers and transaction types.

---

## AI Safety

The AI analyst is instructed to:

- State clearly that outputs are informational, **not financial advice**.
- Avoid explicit buy/sell recommendations (only general risk observations).
- Never hallucinate market news; reason only from uploaded transactions,
  computed metrics, and yfinance price data.
- Say when it lacks enough information.
- For "why is my portfolio down today?", compare latest vs previous close per
  holding and identify the biggest dollar contributors — strictly from price
  data, with no invented external news.
