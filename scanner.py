"""
GarAI Intraday Scanner
======================
Scans US stocks during market hours for two trade setups:

Mode 1 — Momentum continuation
  Stocks with accelerating intraday price + volume movement.
  Same-day exit before 21:00 BST (market close).

Mode 2 — Support / resistance level plays
  Stocks approaching a horizontal level that has been tested
  2+ times over the past 6 months. ATR-grounded stop-loss
  calculated and logged for every candidate.

Schedule: every 30 mins, 14:30–21:00 BST (Mon–Fri)
Stack:    Python / yfinance / pandas / GitHub Actions / Streamlit
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import pytz
import os
import warnings
warnings.filterwarnings("ignore")

# ── Configuration ────────────────────────────────────────────────────────────

TICKERS_FILE      = "tickers.txt"
OUTPUT_FILE       = "output/intraday.csv"
LOOKBACK_DAYS     = 180          # 6 months of daily data for level detection
LEVEL_BAND_PCT    = 0.015        # ±1.5% band to cluster price touches
MIN_TOUCHES       = 3            # minimum touches to count as a valid level
ATR_PERIOD        = 14           # days for ATR calculation
ATR_STOP_MULT     = 1.0          # how many ATRs below support = stop-loss
MOMENTUM_MIN_PCT  = 5.0          # min % move from open to flag Mode 1
RVOL_MIN          = 5.0          # min relative volume for Mode 1
NEAR_LEVEL_PCT    = 0.03         # within 3% of a level = "near" for Mode 2
MODE1_START_BST   = 14           # earliest hour (BST) to flag Mode 1 entries
MODE1_END_BST     = 19           # latest hour (BST) — after this momentum unreliable
MODE2_TOUCH_EXACT = 4            # kept for reference — find_levels now uses >= MIN_TOUCHES
MAX_TICKERS       = 400          # cap to stay within yfinance rate limits
RSI_MIN_MODE1     = 70           # backtest: RSI 70+ = 54% WR vs 39% below 40
RSI_AVOID_MODE1   = 40           # below this = skip Mode 1 signal entirely

BST = pytz.timezone("Europe/London")

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_tickers(path):
    """
    Load tickers from file. With 6,892 tickers we can't scan all of them
    via yfinance in one run (rate limits). Strategy:
    - Load all tickers
    - Rotate through them in blocks across the day using current time as seed
    - Each 30-min run covers a different slice, ensuring full coverage across runs
    - This way every ticker gets scanned at least once every 8-9 hours
    """
    with open(path) as f:
        all_tickers = [line.strip() for line in f if line.strip()]

    total = len(all_tickers)
    if total <= MAX_TICKERS:
        return all_tickers

    # Rotate based on current 30-min slot — different slice each run
    now = datetime.now(BST)
    slot = (now.hour * 2 + now.minute // 30)  # 0-47 slots per day
    start = (slot * MAX_TICKERS) % total
    end = start + MAX_TICKERS

    if end <= total:
        return all_tickers[start:end]
    else:
        # Wrap around
        return all_tickers[start:] + all_tickers[:end - total]


def market_is_open():
    """Return True during NYSE session: 14:30–21:00 BST Mon–Fri."""
    now_bst = datetime.now(BST)
    if now_bst.weekday() >= 5:
        return False
    open_time  = now_bst.replace(hour=14, minute=30, second=0, microsecond=0)
    close_time = now_bst.replace(hour=21, minute=0,  second=0, microsecond=0)
    return open_time <= now_bst <= close_time


def calc_atr(hist, period=ATR_PERIOD):
    """Average True Range over `period` days."""
    high  = hist["High"]
    low   = hist["Low"]
    close = hist["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low  - close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


def find_levels(hist):
    """
    Identify horizontal support/resistance levels from daily OHLC data.

    Method:
      - Collect all daily highs and lows as candidate price points.
      - Cluster points that fall within LEVEL_BAND_PCT of each other.
      - Levels with MIN_TOUCHES or more touches are kept.
      - Returns list of dicts: {price, touches, lowest_at_level, level_type}
    """
    prices = pd.concat([hist["High"], hist["Low"]]).dropna().values
    current_price = hist["Close"].iloc[-1]

    if len(prices) < 10:
        return []

    levels = []
    used = np.zeros(len(prices), dtype=bool)

    for i, p in enumerate(prices):
        if used[i]:
            continue
        band_lo = p * (1 - LEVEL_BAND_PCT)
        band_hi = p * (1 + LEVEL_BAND_PCT)
        mask = (prices >= band_lo) & (prices <= band_hi)
        touches = mask.sum()
        if touches >= MIN_TOUCHES:
            cluster_prices = prices[mask]
            level_price = float(np.median(cluster_prices))
            lowest_at   = float(cluster_prices.min())
            used[mask]  = True

            # Determine whether this is support or resistance
            if level_price < current_price:
                level_type = "support"
            else:
                level_type = "resistance"

            levels.append({
                "price":          round(level_price, 4),
                "touches":        int(touches),
                "lowest_at_level": round(lowest_at, 4),
                "level_type":     level_type,
            })

    return levels


def score_momentum(ticker, hist_daily, intraday):
    """
    Mode 1: Momentum continuation scoring.

    Signals:
      1. Price change from today's open (raw momentum %)
      2. Intraday RVOL — volume so far vs average volume at this time of day
      3. Slope — is price still accelerating? (last 3 candles trending up)

    Returns a score 0–10 and a reason string. Returns None if below threshold.
    """
    try:
        if intraday is None or len(intraday) < 6:
            return None

        today_open  = intraday["Open"].iloc[0]
        current     = intraday["Close"].iloc[-1]
        pct_from_open = (current - today_open) / today_open * 100

        if pct_from_open < MOMENTUM_MIN_PCT:
            return None

        # Time window filter — Mode 1 win rate collapses after 19:00 BST
        now_bst = datetime.now(BST)
        if not (MODE1_START_BST <= now_bst.hour < MODE1_END_BST):
            return None

        # RVOL: compare volume so far today vs average volume for same
        # number of candles at this point in prior sessions
        avg_daily_vol = hist_daily["Volume"].tail(20).mean()
        candles_today = len(intraday)
        # Approximate: full session = ~78 x 5-min candles
        expected_frac = candles_today / 78
        expected_vol_now = avg_daily_vol * expected_frac
        vol_today = intraday["Volume"].sum()
        rvol = vol_today / expected_vol_now if expected_vol_now > 0 else 0

        if rvol < RVOL_MIN:
            return None

        # RSI filter — backtest: RSI 70+ = 54% WR, RSI <40 = 39% WR
        # Calculate RSI(14) from daily close prices
        rsi_val = None
        rsi_badge = ""
        try:
            closes = hist_daily["Close"].tail(20)
            delta = closes.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi_val = round(float(rsi_series.iloc[-1]), 1)
            if rsi_val < RSI_AVOID_MODE1:
                return None   # Hard block — 39% WR, not worth trading
            rsi_badge = f" · RSI {rsi_val}"
        except Exception:
            pass  # RSI unavailable — allow signal without filter

        # Score: momentum + volume only
        # Acceleration signal removed — backtest showed it actively hurts win rate
        momentum_score = min(pct_from_open / 10 * 5, 5)   # up to 5 pts
        rvol_score     = min((rvol - 1) / 3 * 5, 5)        # up to 5 pts (increased from 3)

        total = round(momentum_score + rvol_score, 2)

        reason = (
            f"Up {round(pct_from_open,2)}% from open · "
            f"RVOL {round(rvol,1)}x{rsi_badge}"
        )

        return {
            "mode":         "MODE1_MOMENTUM",
            "score":        total,
            "pct_from_open": round(pct_from_open, 2),
            "rvol":         round(rvol, 2),
            "rsi_at_signal": rsi_val,
            "entry_note":   "Enter on continuation · exit before 21:00 BST",
            "stop_loss":    None,
            "stop_reason":  None,
            "reason":       reason,
        }

    except Exception:
        return None


def score_levels(ticker, hist_daily, intraday):
    """
    Mode 2: Support / resistance level play scoring.

    For each valid level near the current price:
      - Calculate distance to level
      - Score on touch count and proximity
      - Compute ATR-grounded stop-loss
      - Determine signal type (bounce entry or resistance warning)

    Returns best scoring level result, or None if nothing near.
    """
    try:
        if hist_daily is None or len(hist_daily) < 20:
            return None

        current = hist_daily["Close"].iloc[-1]
        atr     = calc_atr(hist_daily)
        levels  = find_levels(hist_daily)

        if not levels:
            return None

        best = None
        best_score = 0

        for lv in levels:
            dist_pct = abs(current - lv["price"]) / lv["price"]

            if dist_pct > NEAR_LEVEL_PCT:
                continue

            # Score: proximity (closer = higher) + touch count strength
            proximity_score = round((1 - dist_pct / NEAR_LEVEL_PCT) * 5, 2)  # 0–5
            touch_score     = min((lv["touches"] - 1) * 1.5, 4)              # 0–4, 3+ touches = max
            total           = round(proximity_score + touch_score, 2)

            if total <= best_score:
                continue

            # Stop-loss: lowest point at level minus ATR buffer
            stop_price  = round(lv["lowest_at_level"] - (ATR_STOP_MULT * atr), 4)
            stop_reason = (
                f"Touches: {lv['touches']} · "
                f"Level low: ${lv['lowest_at_level']} · "
                f"ATR({ATR_PERIOD}): ${round(atr,2)} · "
                f"Stop: ${stop_price}"
            )

            if lv["level_type"] == "support":
                signal      = "SUPPORT_BOUNCE"
                entry_note  = f"Near support ${lv['price']} · enter on bounce candle · can hold multi-day"
            else:
                signal      = "RESISTANCE_WARNING"
                entry_note  = f"Near resistance ${lv['price']} · consider exit or avoid entry"

            reason = (
                f"{lv['touches']} touches at ${lv['price']} · "
                f"{round(dist_pct*100,1)}% away · "
                f"ATR ${round(atr,2)}"
            )

            best_score = total
            best = {
                "mode":          signal,
                "score":         total,
                "level_price":   lv["price"],
                "level_touches": lv["touches"],
                "level_type":    lv["level_type"],
                "dist_pct":      round(dist_pct * 100, 2),
                "atr":           round(atr, 2),
                "stop_loss":     stop_price,
                "stop_reason":   stop_reason,
                "entry_note":    entry_note,
                "reason":        reason,
            }

        return best

    except Exception:
        return None


def scan_ticker(ticker):
    """Fetch data and run both scoring engines for one ticker."""
    try:
        tk = yf.Ticker(ticker)

        # 6 months of daily data for level detection + ATR
        hist_daily = tk.history(period="6mo", interval="1d", auto_adjust=True)
        if hist_daily is None or len(hist_daily) < 20:
            return []

        # Today's intraday data (5-min candles)
        hist_intraday = tk.history(period="1d", interval="5m", auto_adjust=True)

        current_price = hist_daily["Close"].iloc[-1]
        scan_time     = datetime.now(BST).strftime("%Y-%m-%d %H:%M BST")

        results = []

        # Mode 1
        m1 = score_momentum(ticker, hist_daily, hist_intraday)
        if m1:
            results.append({
                "scan_time":    scan_time,
                "ticker":       ticker,
                "price":        round(current_price, 4),
                **m1,
            })

        # Mode 2
        m2 = score_levels(ticker, hist_daily, hist_intraday)
        if m2:
            results.append({
                "scan_time":    scan_time,
                "ticker":       ticker,
                "price":        round(current_price, 4),
                "pct_from_open": None,
                "rvol":         None,
                "accelerating": None,
                "level_price":  m2.get("level_price"),
                "level_touches": m2.get("level_touches"),
                "level_type":   m2.get("level_type"),
                "dist_pct":     m2.get("dist_pct"),
                "atr":          m2.get("atr"),
                **{k: v for k, v in m2.items() if k not in ("level_price","level_touches","level_type","dist_pct","atr")},
            })

        return results

    except Exception:
        return []


def run_scan():
    tickers = load_tickers(TICKERS_FILE)
    print(f"[{datetime.now(BST).strftime('%H:%M BST')}] Scanning {len(tickers)} tickers...")

    all_results = []
    for i, ticker in enumerate(tickers):
        rows = scan_ticker(ticker)
        all_results.extend(rows)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(tickers)} done...")

    if not all_results:
        print("No candidates found this scan.")
        # Write empty file so dashboard doesn't error
        df = pd.DataFrame(columns=[
            "scan_time","ticker","price","mode","score",
            "pct_from_open","rvol","accelerating",
            "level_price","level_touches","level_type","dist_pct","atr",
            "stop_loss","stop_reason","entry_note","reason"
        ])
    else:
        df = pd.DataFrame(all_results)
        df = df.sort_values("score", ascending=False)

    os.makedirs("output", exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} candidates to {OUTPUT_FILE}")
    if len(df):
        print(df[["ticker","mode","score","price","reason"]].head(10).to_string(index=False))


if __name__ == "__main__":
    run_scan()
