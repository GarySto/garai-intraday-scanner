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

# ── Header ─────────────────────────────────────────────────────────────────────

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

# ── Load data ──────────────────────────────────────────────────────────────────

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

last_scan = df["scan_time"].iloc[0] if "scan_time" in df.columns else "Unknown"
st.markdown(f"**Last scan:** {last_scan} &nbsp;·&nbsp; **{len(df)} candidates found**")

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🚀 Momentum",
    "🟢 Support bounces",
    "🔴 Resistance warnings",
    "📊 Backtest Explorer",
    "📒 Trade Tracker",
])

df_m1      = df[df["mode"] == "MODE1_MOMENTUM"].copy()
df_support = df[df["mode"] == "SUPPORT_BOUNCE"].copy()
df_resist  = df[df["mode"] == "RESISTANCE_WARNING"].copy()

# ── Score colour helper ────────────────────────────────────────────────────────

def score_style_green(v):
    if isinstance(v, (int, float)):
        alpha = min(v, 10) / 10
        return f"background-color: rgba(99,153,34,{alpha:.2f}); color: white"
    return ""

def score_style_red(v):
    if isinstance(v, (int, float)):
        alpha = min(v, 10) / 10
        return f"background-color: rgba(216,90,48,{alpha:.2f}); color: white"
    return ""

# ── Tab 1: Momentum ────────────────────────────────────────────────────────────

with tab1:
    st.subheader("🚀 Mode 1 — Momentum continuation")
    st.caption("Stocks accelerating intraday with above-average volume. Same-day exit before 21:00 BST.")
    try:
        import signal_cards
        signal_cards.render_mode1(df_m1)
    except Exception as e:
        st.error(f"Signal card error: {e}")
        if not df_m1.empty:
            cols_m1 = [c for c in ["ticker","price","score","pct_from_open","rvol"] if c in df_m1.columns]
            st.dataframe(df_m1[cols_m1], use_container_width=True, hide_index=True)

# ── Tab 2: Support bounces ─────────────────────────────────────────────────────

with tab2:
    st.subheader("🟢 Mode 2 — Support bounce candidates")
    st.caption("Near a horizontal support level tested 2+ times over 6 months. ATR stop-loss calculated.")
    try:
        import signal_cards
        signal_cards.render_mode2(df_support)
    except Exception as e:
        st.error(f"Signal card error: {e}")
        if not df_support.empty:
            cols_s = [c for c in ["ticker","price","score","level_price","level_touches","stop_loss"] if c in df_support.columns]
            st.dataframe(df_support[cols_s], use_container_width=True, hide_index=True)

# ── Tab 3: Resistance warnings ─────────────────────────────────────────────────

with tab3:
    st.subheader("🔴 Mode 2 — Resistance warnings")
    st.caption("Near a horizontal resistance level. Consider exiting existing positions or avoiding entry.")
    try:
        import signal_cards
        signal_cards.render_resistance(df_resist)
    except Exception as e:
        st.error(f"Signal card error: {e}")
        if not df_resist.empty:
            cols_r = [c for c in ["ticker","price","score","level_price","level_touches","dist_pct"] if c in df_resist.columns]
            st.dataframe(df_resist[cols_r], use_container_width=True, hide_index=True)

# ── Tab 4: Backtest Explorer ───────────────────────────────────────────────────

with tab4:
    try:
        import backtest_explorer
        backtest_explorer.render()
    except ImportError:
        st.warning("backtest_explorer.py not found in repo root.")
    except Exception as e:
        st.error(f"Backtest Explorer error: {e}")

# ── Tab 5: Trade Tracker ───────────────────────────────────────────────────────

with tab5:
    try:
        import trade_tracker
        trade_tracker.render()
    except ImportError:
        st.warning("trade_tracker.py not found in repo root.")
    except Exception as e:
        st.error(f"Trade Tracker error: {e}")

# ── Footer ─────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "GarAI Intraday Scanner · Built with Python, yfinance, GitHub Actions & Streamlit · "
    "Not financial advice · Real money, real rules, real data."
)
