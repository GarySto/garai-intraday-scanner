"""
GarAI — Trade Tracker
======================
A self-contained Streamlit page. Add to streamlit_app.py as tab 5:

    with tab5:
        import trade_tracker
        trade_tracker.render()

Data stored in two CSVs committed to the repo root:
    trades_open.csv    — currently open positions
    trades_closed.csv  — closed trades log (taken + skipped)

MACD logic:
    - Calculates from D:\\GarAI\\data\\technicals\\ if available (home PC)
    - Falls back to manual input field when D drive not present (Streamlit Cloud / office)
    - Both paths log the MACD value + source to the CSV
"""

import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime, date, timedelta
import pytz

BST = pytz.timezone("Europe/London")

# ── Paths ──────────────────────────────────────────────────────────────────────
OPEN_CSV   = "trades_open.csv"
CLOSED_CSV = "trades_closed.csv"
TECH_DIR   = r"D:\GarAI\data\technicals"

# ── Colours ────────────────────────────────────────────────────────────────────
C_PURPLE = "#7F77DD"
C_TEAL   = "#1D9E75"
C_CORAL  = "#D85A30"
C_AMBER  = "#EF9F27"
C_GRAY   = "#888780"

# ── Open trades columns ────────────────────────────────────────────────────────
OPEN_COLS = [
    "trade_id", "date_entered", "ticker", "mode",
    "entry_price", "current_price", "position_size_gbp",
    "stop_loss", "target_3pct", "target_5pct",
    "level_price", "level_touches", "atr",
    "rsi_at_entry", "macd_at_entry", "macd_source",
    "score", "market_regime", "event_name",
    "notes", "status",
]

# ── Closed trades columns ──────────────────────────────────────────────────────
CLOSED_COLS = [
    "trade_id", "date_entered", "date_closed", "ticker", "mode", "trade_type",
    "entry_price", "exit_price", "position_size_gbp",
    "stop_loss", "target_3pct", "target_5pct",
    "pnl_pct", "pnl_gbp", "exit_reason",
    "rsi_at_entry", "macd_at_entry", "macd_at_exit", "macd_source",
    "score", "market_regime", "event_name",
    "days_held", "hit_stop", "hit_target_3", "hit_target_5",
    "notes", "skip_reason", "actual_outcome_pct",
]

# ── Data I/O ───────────────────────────────────────────────────────────────────

def load_open():
    if os.path.exists(OPEN_CSV):
        try:
            df = pd.read_csv(OPEN_CSV)
            for col in OPEN_COLS:
                if col not in df.columns:
                    df[col] = None
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=OPEN_COLS)


def load_closed():
    if os.path.exists(CLOSED_CSV):
        try:
            df = pd.read_csv(CLOSED_CSV)
            for col in CLOSED_COLS:
                if col not in df.columns:
                    df[col] = None
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=CLOSED_COLS)


def save_open(df):
    df.to_csv(OPEN_CSV, index=False)


def save_closed(df):
    df.to_csv(CLOSED_CSV, index=False)


def next_trade_id(open_df, closed_df):
    ids = []
    for df in [open_df, closed_df]:
        if not df.empty and "trade_id" in df.columns:
            ids.extend(df["trade_id"].dropna().tolist())
    nums = []
    for tid in ids:
        try:
            nums.append(int(str(tid).replace("T", "")))
        except Exception:
            pass
    return f"T{max(nums) + 1:04d}" if nums else "T0001"


# ── MACD calculation from D drive ──────────────────────────────────────────────

def calc_macd_from_local(ticker):
    """
    Reads from D:\\GarAI\\data\\technicals\\{ticker}_macd.csv if available.
    Returns (macd_signal: str, source: str) where signal is 'bullish'/'bearish'/None
    """
    path = os.path.join(TECH_DIR, f"{ticker}_macd.csv")
    if not os.path.exists(path):
        return None, "not_available"
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df = df.sort_index()
        macd_cols = [c for c in df.columns if "macd" in c.lower() and "signal" not in c.lower()]
        sig_cols  = [c for c in df.columns if "signal" in c.lower()]
        if not macd_cols or not sig_cols:
            return None, "column_missing"
        last = df.iloc[-1]
        macd_val = float(last[macd_cols[0]])
        sig_val  = float(last[sig_cols[0]])
        result = "bullish" if macd_val > sig_val else "bearish"
        return result, "d_drive"
    except Exception:
        return None, "error"


def macd_badge(signal, source):
    if signal == "bullish":
        colour = C_TEAL
        label = "MACD bullish"
    elif signal == "bearish":
        colour = C_CORAL
        label = "MACD bearish"
    else:
        colour = C_GRAY
        label = "MACD unknown"
    src_label = " (D drive)" if source == "d_drive" else " (manual)" if source == "manual" else " (unavailable)"
    return colour, label + src_label


# ── Status calculation ─────────────────────────────────────────────────────────

def calc_trade_status(row):
    """Returns dict of computed fields for an open trade row."""
    out = {}
    try:
        entry   = float(row.get("entry_price", 0) or 0)
        current = float(row.get("current_price", 0) or 0)
        stop    = float(row.get("stop_loss", 0) or 0)
        t3      = float(row.get("target_3pct", 0) or 0)
        t5      = float(row.get("target_5pct", 0) or 0)
        size    = float(row.get("position_size_gbp", 0) or 0)

        if entry > 0 and current > 0:
            pct = (current - entry) / entry * 100
            out["pct_move"] = round(pct, 2)
            out["pnl_gbp_est"] = round(size * pct / 100, 2)
        else:
            out["pct_move"] = None
            out["pnl_gbp_est"] = None

        if entry > 0 and stop > 0:
            out["pct_to_stop"] = round((stop - current) / entry * 100, 2) if current > 0 else None
        else:
            out["pct_to_stop"] = None

        if entry > 0 and t3 > 0 and current > 0:
            out["pct_to_t3"] = round((t3 - current) / current * 100, 2)
        else:
            out["pct_to_t3"] = None

        if entry > 0 and t5 > 0 and current > 0:
            out["pct_to_t5"] = round((t5 - current) / current * 100, 2)
        else:
            out["pct_to_t5"] = None

        if row.get("date_entered"):
            try:
                entered = pd.to_datetime(row["date_entered"]).date()
                out["days_held"] = (date.today() - entered).days
            except Exception:
                out["days_held"] = None
        else:
            out["days_held"] = None

    except Exception:
        out = {"pct_move": None, "pnl_gbp_est": None,
               "pct_to_stop": None, "pct_to_t3": None,
               "pct_to_t5": None, "days_held": None}
    return out


# ── Colour helpers ─────────────────────────────────────────────────────────────

def pct_colour(val, invert=False):
    if val is None:
        return C_GRAY
    if invert:
        return C_CORAL if val > 0 else C_TEAL
    return C_TEAL if val > 0 else C_CORAL


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render():
    st.markdown("## Trade Tracker")
    st.caption("Log and monitor open positions, skipped signals, and closed trades. "
               "MACD auto-calculates from your D drive when available, or enter manually.")

    open_df   = load_open()
    closed_df = load_closed()

    now_bst = datetime.now(BST)
    regime_note = ""

    tab_open, tab_log, tab_skip, tab_closed, tab_stats = st.tabs([
        "Open positions",
        "Log a trade",
        "Log skipped signal",
        "Closed trades",
        "Performance",
    ])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 — OPEN POSITIONS
    # ══════════════════════════════════════════════════════════════════════
    with tab_open:
        if open_df.empty:
            st.info("No open positions logged yet. Use 'Log a trade' to add your first entry.")
        else:
            st.markdown(f"**{len(open_df)} open position{'s' if len(open_df) != 1 else ''}**")

            for idx, row in open_df.iterrows():
                ticker  = str(row.get("ticker", "?"))
                mode    = str(row.get("mode", ""))
                trade_id = str(row.get("trade_id", ""))
                status  = calc_trade_status(row)
                pct     = status["pct_move"]
                pnl     = status["pnl_gbp_est"]
                days    = status["days_held"]
                to_stop = status["pct_to_stop"]
                to_t3   = status["pct_to_t3"]
                to_t5   = status["pct_to_t5"]

                macd_stored = str(row.get("macd_at_entry", "")) or ""
                macd_src    = str(row.get("macd_source", "")) or ""

                # Attempt live recalc from D drive
                macd_live, macd_live_src = calc_macd_from_local(ticker)

                with st.expander(
                    f"{ticker}  ·  {trade_id}  ·  "
                    f"{'▲' if (pct or 0) >= 0 else '▼'} "
                    f"{abs(pct):.2f}%  ·  "
                    f"Day {days or '?'}"
                ):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Entry", f"${float(row.get('entry_price', 0) or 0):.4f}")
                    c2.metric("Current", f"${float(row.get('current_price', 0) or 0):.4f}",
                              delta=f"{pct:+.2f}%" if pct is not None else None)
                    c3.metric("Est. P&L", f"£{pnl:+.2f}" if pnl is not None else "—")
                    c4.metric("Days held", str(days) if days is not None else "—")

                    st.markdown("---")

                    # Target / stop levels
                    c5, c6, c7 = st.columns(3)
                    stop_val = float(row.get("stop_loss", 0) or 0)
                    t3_val   = float(row.get("target_3pct", 0) or 0)
                    t5_val   = float(row.get("target_5pct", 0) or 0)

                    stop_delta = f"{to_stop:+.2f}% away" if to_stop is not None else None
                    t3_delta   = f"{to_t3:+.2f}% away" if to_t3 is not None else None
                    t5_delta   = f"{to_t5:+.2f}% away" if to_t5 is not None else None

                    c5.metric("Stop-loss", f"${stop_val:.4f}", delta=stop_delta,
                              delta_color="inverse")
                    c6.metric("+3% target", f"${t3_val:.4f}", delta=t3_delta)
                    c7.metric("+5% target", f"${t5_val:.4f}", delta=t5_delta)

                    # MACD section
                    st.markdown("---")
                    st.markdown("**MACD status**")

                    macd_col1, macd_col2 = st.columns(2)

                    with macd_col1:
                        if macd_live:
                            colour = C_TEAL if macd_live == "bullish" else C_CORAL
                            st.markdown(
                                f'<span style="color:{colour};font-weight:500">'
                                f'Live: {macd_live.upper()} (from D drive)</span>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.caption("D drive MACD not available — enter manually below")
                            manual_macd = st.selectbox(
                                "MACD now",
                                ["—", "bullish", "bearish"],
                                key=f"macd_manual_{idx}",
                            )
                            if manual_macd != "—" and st.button(
                                "Save MACD", key=f"save_macd_{idx}"
                            ):
                                open_df.at[idx, "macd_at_entry"] = manual_macd
                                open_df.at[idx, "macd_source"]   = "manual"
                                save_open(open_df)
                                st.success("MACD saved.")
                                st.rerun()

                    with macd_col2:
                        if macd_stored and macd_stored not in ("None", "nan", ""):
                            colour = C_TEAL if macd_stored == "bullish" else C_CORAL
                            src_label = "D drive" if macd_src == "d_drive" else "manual"
                            st.markdown(
                                f'<span style="color:{colour};font-weight:500">'
                                f'At entry: {macd_stored.upper()} ({src_label})</span>',
                                unsafe_allow_html=True,
                            )

                    # Exit actions
                    st.markdown("---")
                    st.markdown("**Update or close**")

                    ua, ub, uc = st.columns(3)

                    new_price = ua.number_input(
                        "Update current price ($)",
                        min_value=0.0,
                        value=float(row.get("current_price") or 0),
                        step=0.01,
                        format="%.4f",
                        key=f"price_update_{idx}",
                    )
                    if ua.button("Update price", key=f"btn_price_{idx}"):
                        open_df.at[idx, "current_price"] = new_price
                        save_open(open_df)
                        st.rerun()

                    exit_reason = ub.selectbox(
                        "Exit reason",
                        ["Stop hit", "+3% target", "+5% target", "Trailing stop",
                         "MACD flip", "Regime change", "Manual — profit",
                         "Manual — loss", "Other"],
                        key=f"exit_reason_{idx}",
                    )
                    exit_price = ub.number_input(
                        "Exit price ($)",
                        min_value=0.0,
                        value=float(row.get("current_price") or 0),
                        step=0.01,
                        format="%.4f",
                        key=f"exit_price_{idx}",
                    )

                    exit_notes = uc.text_area(
                        "Exit notes", key=f"exit_notes_{idx}", height=68
                    )
                    macd_at_exit = uc.selectbox(
                        "MACD at exit",
                        ["—", "bullish", "bearish"],
                        key=f"macd_exit_{idx}",
                    )

                    if ub.button("Close trade", key=f"close_{idx}", type="primary"):
                        entry_p  = float(row.get("entry_price") or 0)
                        size_gbp = float(row.get("position_size_gbp") or 0)
                        pnl_pct  = (exit_price - entry_p) / entry_p * 100 if entry_p else 0
                        pnl_gbp  = size_gbp * pnl_pct / 100

                        entered = pd.to_datetime(row.get("date_entered", date.today())).date()
                        days_h  = (date.today() - entered).days

                        closed_row = {
                            "trade_id":       row.get("trade_id"),
                            "date_entered":   row.get("date_entered"),
                            "date_closed":    date.today().isoformat(),
                            "ticker":         ticker,
                            "mode":           mode,
                            "trade_type":     "taken",
                            "entry_price":    entry_p,
                            "exit_price":     exit_price,
                            "position_size_gbp": size_gbp,
                            "stop_loss":      row.get("stop_loss"),
                            "target_3pct":    row.get("target_3pct"),
                            "target_5pct":    row.get("target_5pct"),
                            "pnl_pct":        round(pnl_pct, 2),
                            "pnl_gbp":        round(pnl_gbp, 2),
                            "exit_reason":    exit_reason,
                            "rsi_at_entry":   row.get("rsi_at_entry"),
                            "macd_at_entry":  row.get("macd_at_entry"),
                            "macd_at_exit":   macd_at_exit if macd_at_exit != "—" else None,
                            "macd_source":    row.get("macd_source"),
                            "score":          row.get("score"),
                            "market_regime":  row.get("market_regime"),
                            "event_name":     row.get("event_name"),
                            "days_held":      days_h,
                            "hit_stop":       exit_reason == "Stop hit",
                            "hit_target_3":   exit_reason == "+3% target",
                            "hit_target_5":   exit_reason == "+5% target",
                            "notes":          exit_notes,
                            "skip_reason":    None,
                            "actual_outcome_pct": round(pnl_pct, 2),
                        }

                        closed_df = pd.concat(
                            [closed_df, pd.DataFrame([closed_row])], ignore_index=True
                        )
                        save_closed(closed_df)
                        open_df = open_df.drop(idx).reset_index(drop=True)
                        save_open(open_df)
                        st.success(f"{ticker} closed — P&L {pnl_pct:+.2f}% (£{pnl_gbp:+.2f})")
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 — LOG A TRADE
    # ══════════════════════════════════════════════════════════════════════
    with tab_log:
        st.markdown("### Log a new trade")
        st.caption("Fill in from the scanner signal. MACD will auto-load from D drive where possible.")

        col1, col2 = st.columns(2)

        with col1:
            ticker_in  = st.text_input("Ticker (e.g. AAPL)", "").upper().strip()
            mode_in    = st.selectbox("Mode", ["SUPPORT_BOUNCE", "MODE1_MOMENTUM", "RESISTANCE_WARNING"])
            entry_in   = st.number_input("Entry price ($)", min_value=0.0, step=0.01, format="%.4f")
            size_in    = st.number_input("Position size (£)", min_value=0.0, step=10.0, format="%.2f")
            stop_in    = st.number_input("Stop-loss ($)", min_value=0.0, step=0.01, format="%.4f")

        with col2:
            score_in   = st.number_input("Scanner score", min_value=0.0, max_value=15.0, step=0.1)
            rsi_in     = st.number_input("RSI at signal", min_value=0.0, max_value=100.0, step=0.1)
            regime_in  = st.selectbox("Market regime", ["Volatile", "Bull", "Bear", "Crisis", "Recovery", "Unknown"])
            event_in   = st.text_input("Active event (e.g. Tariff negotiation)", "None")
            notes_in   = st.text_area("Notes", height=80)

        # MACD — auto-load from D drive
        macd_signal = None
        macd_source = "not_available"
        if ticker_in:
            macd_signal, macd_source = calc_macd_from_local(ticker_in)

        st.markdown("**MACD at entry**")
        if macd_signal and macd_source == "d_drive":
            colour = C_TEAL if macd_signal == "bullish" else C_CORAL
            st.markdown(
                f'<span style="color:{colour};font-weight:500">'
                f'Auto-calculated from D drive: {macd_signal.upper()}</span>',
                unsafe_allow_html=True,
            )
        else:
            if ticker_in:
                st.caption(f"D drive data not found for {ticker_in} — enter manually:")
            macd_manual = st.selectbox("MACD (manual)", ["—", "bullish", "bearish"])
            if macd_manual != "—":
                macd_signal = macd_manual
                macd_source = "manual"

        # Auto-calculate targets
        t3 = round(entry_in * 1.03, 4) if entry_in > 0 else 0.0
        t5 = round(entry_in * 1.05, 4) if entry_in > 0 else 0.0

        if entry_in > 0:
            st.info(f"+3% target: ${t3:.4f}  ·  +5% target: ${t5:.4f}  ·  "
                    f"Stop at ${stop_in:.4f} = "
                    f"{((stop_in - entry_in) / entry_in * 100):+.2f}% from entry")

        if st.button("Log trade", type="primary", disabled=(ticker_in == "" or entry_in == 0)):
            trade_id = next_trade_id(open_df, closed_df)
            new_row = {
                "trade_id":          trade_id,
                "date_entered":      date.today().isoformat(),
                "ticker":            ticker_in,
                "mode":              mode_in,
                "entry_price":       entry_in,
                "current_price":     entry_in,
                "position_size_gbp": size_in,
                "stop_loss":         stop_in,
                "target_3pct":       t3,
                "target_5pct":       t5,
                "level_price":       None,
                "level_touches":     None,
                "atr":               None,
                "rsi_at_entry":      rsi_in,
                "macd_at_entry":     macd_signal,
                "macd_source":       macd_source,
                "score":             score_in,
                "market_regime":     regime_in,
                "event_name":        event_in,
                "notes":             notes_in,
                "status":            "open",
            }
            open_df = pd.concat([open_df, pd.DataFrame([new_row])], ignore_index=True)
            save_open(open_df)
            st.success(f"{ticker_in} logged as {trade_id}. "
                       f"MACD: {macd_signal or 'not set'} ({macd_source})")
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 — SKIPPED SIGNALS
    # ══════════════════════════════════════════════════════════════════════
    with tab_skip:
        st.markdown("### Log a skipped signal")
        st.caption("Record signals you saw but chose not to take. "
                   "This tracks whether your human overrides add or destroy value over time.")

        sc1, sc2 = st.columns(2)

        with sc1:
            sk_ticker  = st.text_input("Ticker", "", key="sk_ticker").upper().strip()
            sk_mode    = st.selectbox("Mode", ["SUPPORT_BOUNCE", "MODE1_MOMENTUM"], key="sk_mode")
            sk_entry   = st.number_input("Signal entry price ($)", min_value=0.0, step=0.01,
                                         format="%.4f", key="sk_entry")
            sk_score   = st.number_input("Scanner score", min_value=0.0, step=0.1, key="sk_score")
            sk_rsi     = st.number_input("RSI at signal", min_value=0.0, max_value=100.0,
                                         step=0.1, key="sk_rsi")

        with sc2:
            sk_reason  = st.selectbox(
                "Why did you skip it?",
                [
                    "Didn't trust the signal",
                    "Already at position limit",
                    "Macro concern / bad regime",
                    "Couldn't watch it (away from desk)",
                    "Earnings risk",
                    "Looked extended / too far moved",
                    "Low conviction — score borderline",
                    "Other",
                ],
                key="sk_reason",
            )
            sk_outcome = st.number_input(
                "Actual outcome % (fill in later if unknown)",
                value=0.0, step=0.1, format="%.2f", key="sk_outcome",
            )
            sk_notes   = st.text_area("Notes", key="sk_notes", height=80)
            sk_regime  = st.selectbox("Market regime at signal",
                                      ["Volatile", "Bull", "Bear", "Crisis", "Recovery", "Unknown"],
                                      key="sk_regime")

        # MACD for skipped
        sk_macd, sk_macd_src = None, "not_available"
        if sk_ticker:
            sk_macd, sk_macd_src = calc_macd_from_local(sk_ticker)
        if not sk_macd:
            sk_macd_manual = st.selectbox("MACD at signal (manual)",
                                          ["—", "bullish", "bearish"], key="sk_macd_man")
            if sk_macd_manual != "—":
                sk_macd = sk_macd_manual
                sk_macd_src = "manual"

        if st.button("Log skipped signal", type="primary",
                     disabled=(sk_ticker == "" or sk_entry == 0)):
            trade_id = next_trade_id(open_df, closed_df)
            skip_row = {
                "trade_id":          trade_id,
                "date_entered":      date.today().isoformat(),
                "date_closed":       date.today().isoformat(),
                "ticker":            sk_ticker,
                "mode":              sk_mode,
                "trade_type":        "skipped",
                "entry_price":       sk_entry,
                "exit_price":        None,
                "position_size_gbp": 0,
                "stop_loss":         None,
                "target_3pct":       round(sk_entry * 1.03, 4) if sk_entry else None,
                "target_5pct":       round(sk_entry * 1.05, 4) if sk_entry else None,
                "pnl_pct":           None,
                "pnl_gbp":           None,
                "exit_reason":       None,
                "rsi_at_entry":      sk_rsi,
                "macd_at_entry":     sk_macd,
                "macd_at_exit":      None,
                "macd_source":       sk_macd_src,
                "score":             sk_score,
                "market_regime":     sk_regime,
                "event_name":        None,
                "days_held":         0,
                "hit_stop":          False,
                "hit_target_3":      False,
                "hit_target_5":      False,
                "notes":             sk_notes,
                "skip_reason":       sk_reason,
                "actual_outcome_pct": sk_outcome,
            }
            closed_df = pd.concat([closed_df, pd.DataFrame([skip_row])], ignore_index=True)
            save_closed(closed_df)
            st.success(f"Skipped signal logged for {sk_ticker} ({trade_id}). "
                       "Update the outcome % later once you know what it did.")
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4 — CLOSED TRADES
    # ══════════════════════════════════════════════════════════════════════
    with tab_closed:
        if closed_df.empty:
            st.info("No closed trades or skipped signals logged yet.")
        else:
            taken   = closed_df[closed_df["trade_type"] == "taken"]
            skipped = closed_df[closed_df["trade_type"] == "skipped"]

            st.markdown(f"**{len(taken)} closed trades · {len(skipped)} skipped signals**")

            view = st.radio("Show", ["Closed trades", "Skipped signals", "Both"],
                            horizontal=True)

            if view in ["Closed trades", "Both"] and not taken.empty:
                st.markdown("#### Closed trades")
                show_cols = [c for c in [
                    "date_entered", "date_closed", "ticker", "mode",
                    "entry_price", "exit_price", "pnl_pct", "pnl_gbp",
                    "exit_reason", "days_held", "macd_at_entry", "macd_at_exit",
                    "market_regime", "notes",
                ] if c in taken.columns]

                def colour_pnl(val):
                    if pd.isna(val):
                        return ""
                    return f"color: {C_TEAL}" if val > 0 else f"color: {C_CORAL}"

                st.dataframe(
                    taken[show_cols].sort_values("date_closed", ascending=False)
                    .style.applymap(colour_pnl, subset=["pnl_pct", "pnl_gbp"]),
                    use_container_width=True, hide_index=True,
                )

            if view in ["Skipped signals", "Both"] and not skipped.empty:
                st.markdown("#### Skipped signals — what actually happened")
                st.caption("Green = you were right to skip. Red = you missed a winner.")
                skip_show = [c for c in [
                    "date_entered", "ticker", "mode", "entry_price",
                    "actual_outcome_pct", "skip_reason", "score",
                    "rsi_at_entry", "macd_at_entry", "market_regime", "notes",
                ] if c in skipped.columns]

                def colour_skip(val):
                    if pd.isna(val):
                        return ""
                    return f"color: {C_CORAL}" if val > 0 else f"color: {C_TEAL}"

                st.dataframe(
                    skipped[skip_show].sort_values("date_entered", ascending=False)
                    .style.applymap(colour_skip, subset=["actual_outcome_pct"]),
                    use_container_width=True, hide_index=True,
                )

            st.markdown("---")
            csv_dl = closed_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download full log as CSV", data=csv_dl,
                               file_name="garai_trades_log.csv", mime="text/csv")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 5 — PERFORMANCE
    # ══════════════════════════════════════════════════════════════════════
    with tab_stats:
        taken = closed_df[closed_df["trade_type"] == "taken"] if not closed_df.empty else pd.DataFrame()
        skipped = closed_df[closed_df["trade_type"] == "skipped"] if not closed_df.empty else pd.DataFrame()

        if taken.empty and skipped.empty:
            st.info("No data yet — log some trades first.")
        else:
            st.markdown("### Your performance vs the system")

            if not taken.empty and "pnl_pct" in taken.columns:
                v = taken["pnl_pct"].dropna()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Trades taken", len(taken))
                c2.metric("Win rate", f"{(v > 0).mean() * 100:.1f}%" if len(v) else "—")
                c3.metric("Avg return", f"{v.mean():+.2f}%" if len(v) else "—")
                c4.metric("Total P&L",
                          f"£{taken['pnl_gbp'].dropna().sum():+.2f}"
                          if "pnl_gbp" in taken.columns else "—")

                st.markdown("---")

                # Exits breakdown
                if "exit_reason" in taken.columns:
                    er = taken["exit_reason"].value_counts()
                    st.markdown("**How trades closed**")
                    for reason, count in er.items():
                        sub = taken[taken["exit_reason"] == reason]["pnl_pct"].dropna()
                        avg = f"{sub.mean():+.2f}%" if len(sub) else "—"
                        st.markdown(f"- {reason}: **{count}** trades · avg {avg}")

                # MACD breakdown
                if "macd_at_entry" in taken.columns:
                    st.markdown("---")
                    st.markdown("**MACD at entry vs outcome**")
                    for sig in ["bullish", "bearish"]:
                        sub = taken[taken["macd_at_entry"] == sig]["pnl_pct"].dropna()
                        if len(sub):
                            wr = f"{(sub > 0).mean() * 100:.1f}%"
                            avg = f"{sub.mean():+.2f}%"
                            st.markdown(f"- MACD {sig} at entry: {len(sub)} trades · "
                                        f"WR {wr} · avg {avg}")

            if not skipped.empty and "actual_outcome_pct" in skipped.columns:
                st.markdown("---")
                st.markdown("### Human override analysis — skipped signals")
                sv = skipped["actual_outcome_pct"].dropna()
                if len(sv):
                    missed_winners = (sv > 3).sum()
                    correct_skips  = (sv <= 0).sum()
                    st.metric("Signals skipped", len(skipped))

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Correct skips (would have lost)", int(correct_skips))
                    c2.metric("Missed winners (>+3%)", int(missed_winners))
                    c3.metric("Avg outcome of skipped",
                              f"{sv.mean():+.2f}%")

                    if missed_winners > correct_skips:
                        st.warning("Your human overrides are net negative — "
                                   "you're skipping more winners than losers.")
                    else:
                        st.success("Your human overrides are net positive — "
                                   "your skips are avoiding more losers than winners.")


if __name__ == "__main__":
    st.set_page_config(page_title="GarAI Trade Tracker",
                       page_icon="", layout="wide")
    render()
