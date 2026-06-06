"""
GarAI Intraday Scanner — Dashboard
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

BST = pytz.timezone("Europe/London")

st.set_page_config(
    page_title="GarAI Intraday Scanner",
    page_icon="📡",
    layout="wide",
)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("📡 GarAI Intraday Scanner")
st.caption(
    "Scans for two setups: **Mode 1 — Momentum continuation** (same-day trade) · "
    "**Mode 2 — Support/resistance level plays** (can hold multi-day)"
)

now_bst = datetime.now(BST)
market_open = (
    now_bst.weekday() < 5
    and now_bst.hour >= 14
    and (now_bst.hour < 21 or (now_bst.hour == 14 and now_bst.minute >= 30))
)
status = "🟢 Market open" if market_open else "🔴 Market closed"
st.markdown(f"**{now_bst.strftime('%A %d %b %Y · %H:%M BST')}** &nbsp;·&nbsp; {status}")

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

CSV_URL = "https://raw.githubusercontent.com/GarySto/garai-intraday-scanner/main/output/intraday.csv"

@st.cache_data(ttl=300)
def load_data():
    try:
        df = pd.read_csv(CSV_URL)
        return df
    except Exception as e:
        return None

df = load_data()

if df is None or df.empty:
    st.info("No candidates yet — scanner runs every 30 minutes during market hours (14:30–21:00 BST).")
    st.stop()

# Last scan time
last_scan = df["scan_time"].iloc[0] if "scan_time" in df.columns else "Unknown"
st.markdown(f"**Last scan:** {last_scan} &nbsp;·&nbsp; **{len(df)} candidates found**")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 Momentum",
    "🟢 Support bounces",
    "🔴 Resistance warnings",
    "📊 Backtest Explorer",
])

# ── Split into modes ──────────────────────────────────────────────────────────

df_m1      = df[df["mode"] == "MODE1_MOMENTUM"].copy()
df_support = df[df["mode"] == "SUPPORT_BOUNCE"].copy()
df_resist  = df[df["mode"] == "RESISTANCE_WARNING"].copy()

# ── Tab 1: Mode 1 Momentum ────────────────────────────────────────────────────

with tab1:
    st.subheader("🚀 Mode 1 — Momentum continuation")
    st.caption("Stocks accelerating intraday with above-average volume. Same-day exit before 21:00 BST.")

    if df_m1.empty:
        st.info("No momentum candidates this scan.")
    else:
        cols_m1 = ["ticker", "price", "score", "pct_from_open", "rvol", "accelerating", "entry_note", "reason"]
        cols_m1 = [c for c in cols_m1 if c in df_m1.columns]

        display_m1 = df_m1[cols_m1].rename(columns={
            "ticker":        "Ticker",
            "price":         "Price ($)",
            "score":         "Score",
            "pct_from_open": "% from open",
            "rvol":          "RVOL",
            "accelerating":  "Accelerating",
            "entry_note":    "Entry note",
            "reason":        "Signal detail",
        })

        st.dataframe(
            display_m1.style.background_gradient(subset=["Score"], cmap="Greens"),
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 2: Support bounces ────────────────────────────────────────────────────

with tab2:
    st.subheader("🟢 Mode 2 — Support bounce candidates")
    st.caption("Near a horizontal support level tested 2+ times over 6 months. ATR stop-loss calculated.")

    if df_support.empty:
        st.info("No support bounce candidates this scan.")
    else:
        cols_s = ["ticker", "price", "score", "level_price", "level_touches", "dist_pct", "atr", "stop_loss", "entry_note", "stop_reason"]
        cols_s = [c for c in cols_s if c in df_support.columns]

        display_s = df_support[cols_s].rename(columns={
            "ticker":        "Ticker",
            "price":         "Price ($)",
            "score":         "Score",
            "level_price":   "Support level ($)",
            "level_touches": "Touches",
            "dist_pct":      "Distance (%)",
            "atr":           "ATR ($)",
            "stop_loss":     "Stop-loss ($)",
            "entry_note":    "Entry note",
            "stop_reason":   "Stop logic",
        })

        st.dataframe(
            display_s.style.background_gradient(subset=["Score"], cmap="Greens"),
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 3: Resistance warnings ────────────────────────────────────────────────

with tab3:
    st.subheader("🔴 Mode 2 — Resistance warnings")
    st.caption("Near a horizontal resistance level. Consider exiting existing positions or avoiding entry.")

    if df_resist.empty:
        st.info("No resistance warnings this scan.")
    else:
        cols_r = ["ticker", "price", "score", "level_price", "level_touches", "dist_pct", "entry_note", "reason"]
        cols_r = [c for c in cols_r if c in df_resist.columns]

        display_r = df_resist[cols_r].rename(columns={
            "ticker":        "Ticker",
            "price":         "Price ($)",
            "score":         "Score",
            "level_price":   "Resistance level ($)",
            "level_touches": "Touches",
            "dist_pct":      "Distance (%)",
            "entry_note":    "Note",
            "reason":        "Signal detail",
        })

        st.dataframe(
            display_r.style.background_gradient(subset=["Score"], cmap="Reds"),
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 4: Backtest Explorer ──────────────────────────────────────────────────

with tab4:
    try:
        import backtest_explorer
        backtest_explorer.render()
    except ImportError:
        st.warning("backtest_explorer.py not found in repo root. Add it alongside this file.")
    except Exception as e:
        st.error(f"Backtest Explorer error: {e}")

st.divider()

# ── Footer ────────────────────────────────────────────────────────────────────

st.caption(
    "GarAI Intraday Scanner · Built with Python, yfinance, GitHub Actions & Streamlit · "
    "Not financial advice · Real money, real rules, real data."
)
