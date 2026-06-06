"""
GarAI — Signal Cards
======================
Drop-in replacement for the raw st.dataframe() calls in streamlit_app.py.
Renders rich signal cards with order type guidance, MACD warnings, and
backtest-derived probability labels.

Usage in streamlit_app.py:
    import signal_cards
    signal_cards.render_mode2(df_support)
    signal_cards.render_mode1(df_m1)
    signal_cards.render_resistance(df_resist)
"""

import streamlit as st
import pandas as pd

# ── Backtest-derived constants ──────────────────────────────────────────────────
# From the 730-day run — used to annotate cards with real probabilities
M2_WR_3D          = 50.8   # Mode 2 support bounce 3d win rate
M2_TARGET3_HIT    = 56.3   # % of signals where +3% was hit in 5d
M2_TARGET5_HIT    = 40.0   # % of signals where +5% was hit in 5d
M2_STOP_HIT_3D    = 20.6   # % of Mode 2 signals hitting stop within 3d
M2_MACD_BULL_WR   = 51.3   # Mode 2 WR when MACD bullish
M2_MACD_BEAR_WR   = 48.2   # Mode 2 WR when MACD bearish
M1_RSI_HIGH_WR    = 54.0   # Mode 1 WR when RSI 70-100
M1_RSI_HIGH_AVG   = 1.17   # Mode 1 avg return when RSI 70-100


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _rsi_badge(rsi):
    """Return (label, css_class) for RSI value."""
    if rsi is None:
        return "RSI —", "gray"
    rsi = _safe_float(rsi)
    if rsi >= 70:
        return f"RSI {rsi:.0f} — strong", "green"
    elif rsi >= 50:
        return f"RSI {rsi:.0f}", "green"
    elif rsi >= 30:
        return f"RSI {rsi:.0f}", "amber"
    else:
        return f"RSI {rsi:.0f} — oversold", "red"


def _macd_badge(macd):
    if macd == "bullish":
        return "MACD bullish", "green"
    elif macd == "bearish":
        return "MACD bearish", "red"
    return "MACD —", "gray"


def _regime_badge(regime):
    if not regime or str(regime) in ("None", "nan", ""):
        return None
    regime = str(regime)
    if regime in ("Bull", "Recovery"):
        return regime, "green"
    elif regime == "Crisis":
        return regime, "red"
    else:
        return regime, "amber"


def _badge_html(label, colour):
    colours = {
        "green": ("background:#E1F5EE;color:#085041"),
        "amber": ("background:#FAEEDA;color:#633806"),
        "red":   ("background:#FAECE7;color:#712B13"),
        "gray":  ("background:#F1EFE8;color:#444441"),
    }
    style = colours.get(colour, colours["gray"])
    return (
        f'<span style="font-size:11px;font-weight:500;padding:3px 10px;'
        f'border-radius:20px;white-space:nowrap;{style}">{label}</span>'
    )


def _metric_html(label, value, colour=None):
    val_style = ""
    if colour == "red":
        val_style = "color:#993C1D"
    elif colour == "green":
        val_style = "color:#0F6E56"
    return (
        f'<div style="background:var(--color-background-secondary);'
        f'border-radius:8px;padding:8px 10px;">'
        f'<div style="font-size:11px;color:var(--color-text-secondary);margin-bottom:2px">{label}</div>'
        f'<div style="font-size:14px;font-weight:500;{val_style}">{value}</div>'
        f'</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — Support bounce cards
# ══════════════════════════════════════════════════════════════════════════════

def render_mode2(df, max_cards=10):
    if df is None or df.empty:
        st.info("No support bounce candidates this scan.")
        return

    df = df.copy()
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)

    shown = min(len(df), max_cards)
    st.caption(
        f"Showing top {shown} of {len(df)} candidates · "
        f"Backtest edge: {M2_WR_3D}% WR at 3d · "
        f"+3% target hits {M2_TARGET3_HIT}% of the time"
    )

    for _, row in df.head(max_cards).iterrows():
        ticker  = str(row.get("ticker", "?"))
        price   = _safe_float(row.get("price"))
        score   = _safe_float(row.get("score"))
        level   = _safe_float(row.get("level_price"))
        touches = int(_safe_float(row.get("level_touches", 4)))
        dist    = _safe_float(row.get("dist_pct"))
        atr     = _safe_float(row.get("atr"))
        stop    = _safe_float(row.get("stop_loss"))
        macd    = str(row.get("macd_signal", "")) if "macd_signal" in row.index else None
        rsi     = row.get("rsi_at_signal")
        regime  = row.get("market_regime", "")

        t3 = round(price * 1.03, 4) if price else 0
        t5 = round(price * 1.05, 4) if price else 0
        risk_pct = ((stop - price) / price * 100) if price and stop else 0

        macd_label, macd_colour = _macd_badge(macd)
        rsi_label, rsi_colour   = _rsi_badge(rsi)
        reg_result = _regime_badge(regime)

        # Build badge row
        badges = _badge_html(macd_label, macd_colour)
        badges += " " + _badge_html(rsi_label, rsi_colour)
        if reg_result:
            badges += " " + _badge_html(reg_result[0], reg_result[1])

        # MACD warning?
        macd_warning = (macd == "bearish")
        crisis_warning = (str(regime) == "Crisis")

        with st.container():
            # Header
            st.markdown(
                f'<div style="display:flex;align-items:flex-start;'
                f'justify-content:space-between;margin-bottom:8px">'
                f'<div>'
                f'<span style="font-size:20px;font-weight:500">{ticker}</span>'
                f'&nbsp;&nbsp;<span style="font-size:15px;color:var(--color-text-secondary)">'
                f'${price:.4f}</span>'
                f'<div style="font-size:12px;color:var(--color-text-secondary);margin-top:2px">'
                f'Support bounce · {touches} touches · Score {score:.2f}</div>'
                f'</div>'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">'
                f'{badges}</div></div>',
                unsafe_allow_html=True,
            )

            # Metrics row
            m1 = _metric_html("Support level", f"${level:.4f}")
            m2 = _metric_html("Distance", f"{dist:.2f}%")
            m3 = _metric_html("ATR stop", f"${stop:.4f}", "red")
            m4 = _metric_html("Risk from entry", f"{risk_pct:.1f}%", "red")
            st.markdown(
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px">'
                f'{m1}{m2}{m3}{m4}</div>',
                unsafe_allow_html=True,
            )

            # Warnings
            if crisis_warning:
                st.error(
                    f"Crisis regime detected. Backtest: 42% WR, avg -1.39%. "
                    f"Strong recommendation: skip this signal entirely."
                )
            elif macd_warning:
                st.warning(
                    f"MACD bearish. Backtest shows this cuts WR from {M2_MACD_BULL_WR}% "
                    f"to {M2_MACD_BEAR_WR}%. Consider waiting for MACD crossover "
                    f"or reducing position size by 50%."
                )
            else:
                st.success(
                    f"MACD bullish — backtest WR {M2_MACD_BULL_WR}% at 3d. "
                    f"+3% target hits {M2_TARGET3_HIT}% of the time."
                )

            # Order guidance
            col_buy, col_sell = st.columns(2)

            with col_buy:
                st.markdown("**Entry — recommended**")
                st.markdown(
                    f"- **Limit order at ${level:.4f}** (support level) — best fill, "
                    f"wait for bounce candle to confirm"
                )
                st.markdown(
                    f"- **Stop limit ${price*1.002:.4f} / ${price*1.005:.4f}** — "
                    f"enter on breakout above current price if you miss the bounce"
                )
                st.caption("Avoid market orders — slippage risk at open")

            with col_sell:
                st.markdown("**Exits — set these on entry**")
                st.markdown(f"- **Stop loss: ${stop:.4f}** — hard stop, no exceptions")
                st.markdown(
                    f"- **Limit sell 75% at ${t3:.4f} (+3%)** — "
                    f"hits {M2_TARGET3_HIT:.0f}% of time"
                )
                st.markdown(
                    f"- **Limit sell remaining 25% at ${t5:.4f} (+5%)** — "
                    f"only if MACD stays bullish"
                )

            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — Momentum cards
# ══════════════════════════════════════════════════════════════════════════════

def render_mode1(df, max_cards=10):
    if df is None or df.empty:
        st.info("No momentum candidates this scan.")
        return

    df = df.copy()
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)

    shown = min(len(df), max_cards)
    st.caption(
        f"Showing top {shown} of {len(df)} candidates · "
        f"RSI 70+ signals: {M1_RSI_HIGH_WR}% WR · "
        f"Same-day exit required before 21:00 BST"
    )

    for _, row in df.head(max_cards).iterrows():
        ticker    = str(row.get("ticker", "?"))
        price     = _safe_float(row.get("price"))
        score     = _safe_float(row.get("score"))
        pct_open  = _safe_float(row.get("pct_from_open"))
        rvol      = _safe_float(row.get("rvol"))
        rsi       = row.get("rsi_at_signal")
        scan_time = str(row.get("scan_time", ""))
        macd      = str(row.get("macd_signal", "")) if "macd_signal" in row.index else None
        atr       = _safe_float(row.get("atr", 0))

        rsi_val = _safe_float(rsi) if rsi is not None else None
        rsi_strong = rsi_val is not None and rsi_val >= 70

        stop_atr = round(price - (atr * 1.5), 4) if price and atr else round(price * 0.97, 4)
        t3 = round(price * 1.03, 4) if price else 0
        t5 = round(price * 1.05, 4) if price else 0

        rsi_label, rsi_colour = _rsi_badge(rsi)
        macd_label, macd_colour = _macd_badge(macd)

        rvol_colour = "green" if rvol >= 5 else "amber"
        rvol_badge = _badge_html(f"RVOL {rvol:.1f}×", rvol_colour)
        pct_badge  = _badge_html(f"+{pct_open:.1f}% from open", "green")

        badges = _badge_html(rsi_label, rsi_colour)
        badges += " " + rvol_badge
        badges += " " + pct_badge
        if macd:
            badges += " " + _badge_html(macd_label, macd_colour)

        with st.container():
            st.markdown(
                f'<div style="display:flex;align-items:flex-start;'
                f'justify-content:space-between;margin-bottom:8px">'
                f'<div>'
                f'<span style="font-size:20px;font-weight:500">{ticker}</span>'
                f'&nbsp;&nbsp;<span style="font-size:15px;color:var(--color-text-secondary)">'
                f'${price:.4f}</span>'
                f'<div style="font-size:12px;color:var(--color-text-secondary);margin-top:2px">'
                f'Momentum · Score {score:.2f} · {scan_time}</div>'
                f'</div>'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">'
                f'{badges}</div></div>',
                unsafe_allow_html=True,
            )

            m1 = _metric_html("Current price", f"${price:.4f}")
            m2 = _metric_html("ATR stop", f"${stop_atr:.4f}", "red")
            m3 = _metric_html("+3% target", f"${t3:.4f}", "green")
            m4 = _metric_html("+5% target", f"${t5:.4f}", "green")
            st.markdown(
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px">'
                f'{m1}{m2}{m3}{m4}</div>',
                unsafe_allow_html=True,
            )

            if rsi_strong:
                st.success(
                    f"RSI {rsi_val:.0f} — strong signal. "
                    f"Backtest: {M1_RSI_HIGH_WR}% WR, avg +{M1_RSI_HIGH_AVG}% at 1h. "
                    f"Best performing Mode 1 filter."
                )
            else:
                st.warning(
                    f"RSI below 70 — weaker signal. Backtest WR drops to 43-48% below RSI 70. "
                    f"Consider skipping or waiting for RSI to strengthen."
                )

            col_buy, col_sell = st.columns(2)

            with col_buy:
                st.markdown("**Entry**")
                st.markdown(f"- **Market order now at ~${price:.4f}** — momentum trade, speed matters")
                st.markdown(f"- Set stop loss immediately on entry: **${stop_atr:.4f}**")
                st.caption("Do not use limit orders for Mode 1 — you'll miss the move")

            with col_sell:
                st.markdown("**Exit — must close before 21:00 BST**")
                st.markdown(f"- **Limit sell at ${t3:.4f} (+3%)** or trailing stop 2% from peak")
                st.markdown(f"- **Hard close by 20:45 BST** regardless of P&L")
                st.caption("Mode 1 is same-day only — never hold overnight")

            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — Resistance warning cards (compact)
# ══════════════════════════════════════════════════════════════════════════════

def render_resistance(df, max_cards=10):
    if df is None or df.empty:
        st.info("No resistance warnings this scan.")
        return

    df = df.copy()
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)

    st.caption(
        f"{len(df)} resistance warnings · "
        "Check if you hold any of these — consider exiting or avoiding entry."
    )

    for _, row in df.head(max_cards).iterrows():
        ticker  = str(row.get("ticker", "?"))
        price   = _safe_float(row.get("price"))
        score   = _safe_float(row.get("score"))
        level   = _safe_float(row.get("level_price"))
        touches = int(_safe_float(row.get("level_touches", 4)))
        dist    = _safe_float(row.get("dist_pct"))

        with st.container():
            st.markdown(
                f'<div style="display:flex;align-items:center;'
                f'justify-content:space-between;padding:10px 0;'
                f'border-bottom:0.5px solid var(--color-border-tertiary)">'
                f'<div>'
                f'<span style="font-size:16px;font-weight:500">{ticker}</span>'
                f'&nbsp;&nbsp;<span style="font-size:13px;color:var(--color-text-secondary)">'
                f'${price:.4f}</span>'
                f'</div>'
                f'<div style="font-size:13px;color:var(--color-text-secondary)">'
                f'Resistance ${level:.4f} · {touches} touches · {dist:.2f}% away · Score {score:.2f}'
                f'</div>'
                f'<div>'
                f'{_badge_html("Near resistance", "red")}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("")
    st.info(
        "If you hold any ticker above: consider a **limit sell at or just below the resistance level**, "
        "or a **stop limit to protect gains** if already profitable. "
        "Resistance levels with 4+ touches have a high probability of rejection."
    )
