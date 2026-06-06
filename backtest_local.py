"""
GarAI Intraday Scanner — Local Backtest
=========================================
Reads from D:\\GarAI\\data\\ instead of calling yfinance.
No rate limits. No internet dependency. Runs in minutes.

Now includes market regime context via market_context.py.

Requires download_eodhd.py to have been run first.

Usage:
  py backtest_local.py

Output:
  backtest_results.csv   — all signals with outcomes + market context
  backtest_summary.txt   — summary by mode and market regime
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import pytz
import os
import warnings
warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────

DATA_ROOT       = r"D:\GarAI\data"
DAILY_DIR       = os.path.join(DATA_ROOT, "daily")
INTRADAY_DIR    = os.path.join(DATA_ROOT, "intraday")
TECH_DIR        = os.path.join(DATA_ROOT, "technicals")
TICKERS_FILE    = "tickers.txt"
OUTPUT_DIR      = "."
LOOKBACK_DAYS   = 365       # up to 2 years available
MAX_TICKERS     = 9999      # no cap — use all local data

# Scanner parameters — keep in sync with scanner.py
MOMENTUM_MIN_PCT  = 5.0
RVOL_MIN          = 5.0
LEVEL_BAND_PCT    = 0.015
MIN_TOUCHES       = 2
NEAR_LEVEL_PCT    = 0.03
ATR_PERIOD        = 14
ATR_STOP_MULT     = 1.0
MODE1_START_BST   = 14
MODE1_END_BST     = 19
MODE2_TOUCH_EXACT = 4

OUTCOME_HOURS   = [1, 2, 4]
MODE2_DAYS      = [1, 3, 5]

BST = pytz.timezone("Europe/London")
UTC = pytz.utc

# ── Data loading ──────────────────────────────────────────────────────────────

def load_tickers():
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                tickers = [l.strip() for l in f if l.strip()]
            available = [t for t in tickers
                        if os.path.exists(os.path.join(DAILY_DIR, f"{t}.csv"))]
            print(f"Tickers in list: {len(tickers)}")
            print(f"Tickers with local data: {len(available)}")
            return available[:MAX_TICKERS]
    raise FileNotFoundError("Cannot find tickers.txt")


def load_daily(ticker):
    path = os.path.join(DAILY_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize(UTC)
        else:
            df.index = df.index.tz_convert(UTC)
        return df.dropna(how="all")
    except Exception:
        return None


def load_intraday(ticker):
    path = os.path.join(INTRADAY_DIR, f"{ticker}_5m.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize(UTC)
        else:
            df.index = df.index.tz_convert(UTC)
        return df.dropna(how="all")
    except Exception:
        return None


def load_rsi(ticker):
    """Load pre-calculated RSI from EODHD technicals folder."""
    path = os.path.join(TECH_DIR, f"{ticker}_rsi.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    except Exception:
        return None


def get_rsi_at_date(ticker, signal_date):
    """Get the RSI value for a ticker on a specific date."""
    rsi_df = load_rsi(ticker)
    if rsi_df is None or rsi_df.empty:
        return None
    try:
        # Find the RSI value on or before the signal date
        rsi_df.index = pd.to_datetime(rsi_df.index)
        past = rsi_df[rsi_df.index.date <= signal_date]
        if past.empty:
            return None
        # RSI column name varies — find it
        rsi_col = [c for c in past.columns if "rsi" in c.lower()]
        if not rsi_col:
            rsi_col = past.columns.tolist()
        return round(float(past[rsi_col[0]].iloc[-1]), 2)
    except Exception:
        return None


# ── Scoring (identical to scanner.py) ────────────────────────────────────────

def calc_atr(hist, period=ATR_PERIOD):
    high  = hist["High"]
    low   = hist["Low"]
    close = hist["Close"].shift(1)
    tr = pd.concat([(high-low), (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return None if np.isnan(val) else val


def find_levels(hist):
    prices  = pd.concat([hist["High"], hist["Low"]]).dropna().values
    current = hist["Close"].iloc[-1]
    if len(prices) < 10:
        return []
    levels, used = [], np.zeros(len(prices), dtype=bool)
    for i, p in enumerate(prices):
        if used[i]:
            continue
        mask = (prices >= p*(1-LEVEL_BAND_PCT)) & (prices <= p*(1+LEVEL_BAND_PCT))
        if mask.sum() >= MIN_TOUCHES and mask.sum() == MODE2_TOUCH_EXACT:
            cluster = prices[mask]
            levels.append({
                "price":           round(float(np.median(cluster)), 4),
                "touches":         int(mask.sum()),
                "lowest_at_level": round(float(cluster.min()), 4),
                "level_type":      "support" if np.median(cluster) < current else "resistance",
            })
            used[mask] = True
    return levels


def score_momentum_at(intraday_slice, hist_daily, scan_hour):
    try:
        if intraday_slice is None or len(intraday_slice) < 6:
            return None
        if not (MODE1_START_BST <= scan_hour < MODE1_END_BST):
            return None
        today_open    = intraday_slice["Open"].iloc[0]
        current       = intraday_slice["Close"].iloc[-1]
        pct_from_open = (current - today_open) / today_open * 100
        if pct_from_open < MOMENTUM_MIN_PCT:
            return None
        avg_vol  = hist_daily["Volume"].tail(20).mean()
        exp_vol  = avg_vol * (len(intraday_slice) / 78)
        rvol     = intraday_slice["Volume"].sum() / exp_vol if exp_vol > 0 else 0
        if rvol < RVOL_MIN:
            return None
        total = round(min(pct_from_open/10*5, 5) + min((rvol-1)/3*5, 5), 2)
        return {
            "mode": "MODE1_MOMENTUM", "score": total,
            "pct_from_open": round(pct_from_open, 2),
            "rvol": round(rvol, 2),
            "entry_price": round(current, 4),
        }
    except Exception:
        return None


def score_levels_at(hist_daily_slice):
    try:
        if hist_daily_slice is None or len(hist_daily_slice) < 20:
            return None
        current = hist_daily_slice["Close"].iloc[-1]
        atr     = calc_atr(hist_daily_slice)
        if atr is None:
            return None
        levels  = find_levels(hist_daily_slice)
        best, best_score = None, 0
        for lv in levels:
            dist_pct = abs(current - lv["price"]) / lv["price"]
            if dist_pct > NEAR_LEVEL_PCT:
                continue
            total = round((1-dist_pct/NEAR_LEVEL_PCT)*5 + min((lv["touches"]-1)*1.5, 4), 2)
            if total <= best_score:
                continue
            best_score = total
            best = {
                "mode":          "SUPPORT_BOUNCE" if lv["level_type"]=="support" else "RESISTANCE_WARNING",
                "score":         total,
                "level_price":   lv["price"],
                "level_touches": lv["touches"],
                "level_type":    lv["level_type"],
                "dist_pct":      round(dist_pct*100, 2),
                "atr":           round(atr, 2),
                "stop_loss":     round(lv["lowest_at_level"]-(ATR_STOP_MULT*atr), 4),
                "entry_price":   round(current, 4),
            }
        return best
    except Exception:
        return None


def measure_outcome_m1(intraday_full, signal_time_utc, entry_price):
    outcomes = {}
    try:
        future = intraday_full[intraday_full.index > signal_time_utc]
        if future.empty:
            return outcomes
        for h in OUTCOME_HOURS:
            w = future[future.index <= signal_time_utc + timedelta(hours=h)]
            if not w.empty:
                ep = w["Close"].iloc[-1]
                outcomes[f"return_{h}h_pct"]   = round((ep-entry_price)/entry_price*100, 2)
                outcomes[f"max_gain_{h}h_pct"] = round((w["High"].max()-entry_price)/entry_price*100, 2)
                outcomes[f"stop_hit_{h}h"]     = bool(w["Low"].min() < entry_price*0.97)
        outcomes["return_eod_pct"]       = round((future["Close"].iloc[-1]-entry_price)/entry_price*100, 2)
        outcomes["max_gain_session_pct"] = round((future["High"].max()-entry_price)/entry_price*100, 2)
    except Exception:
        pass
    return outcomes


def measure_outcome_m2(daily_full, signal_date, entry_price, stop_price):
    outcomes = {}
    try:
        future = daily_full[daily_full.index.date > signal_date]
        if future.empty:
            return outcomes
        for d in MODE2_DAYS:
            w = future.head(d)
            if not w.empty:
                ep = w["Close"].iloc[-1]
                outcomes[f"return_{d}d_pct"]   = round((ep-entry_price)/entry_price*100, 2)
                outcomes[f"max_gain_{d}d_pct"] = round((w["High"].max()-entry_price)/entry_price*100, 2)
                if stop_price:
                    outcomes[f"stop_hit_{d}d"] = bool(w["Low"].min() < stop_price)
    except Exception:
        pass
    return outcomes


# ── Process one ticker ────────────────────────────────────────────────────────

def process_ticker(ticker, trade_days):
    signals = []
    try:
        daily_full    = load_daily(ticker)
        intraday_full = load_intraday(ticker)

        if daily_full is None or len(daily_full) < 30:
            return signals

        for trade_day in trade_days:
            session_start = datetime(trade_day.year, trade_day.month, trade_day.day,
                                     13, 30, tzinfo=UTC)
            session_end   = datetime(trade_day.year, trade_day.month, trade_day.day,
                                     20,  0, tzinfo=UTC)

            # Mode 1
            if intraday_full is not None:
                day_intraday = intraday_full[
                    (intraday_full.index.date == trade_day) &
                    (intraday_full.index >= session_start)
                ]
                if not day_intraday.empty:
                    slice_daily = daily_full[daily_full.index.date < trade_day]
                    if len(slice_daily) >= 20:
                        scan_times = pd.date_range(
                            start=session_start + timedelta(minutes=30),
                            end=session_end, freq="30min", tz=UTC
                        )
                        for scan_time in scan_times:
                            sl = day_intraday[day_intraday.index <= scan_time]
                            if len(sl) < 6:
                                continue
                            hour_bst = scan_time.astimezone(BST).hour
                            m1 = score_momentum_at(sl, slice_daily, hour_bst)
                            if m1:
                                outcomes = measure_outcome_m1(day_intraday, scan_time, m1["entry_price"])
                                # Add RSI at signal time
                                rsi = get_rsi_at_date(ticker, trade_day)
                                signals.append({
                                    "date": trade_day.isoformat(),
                                    "scan_time": scan_time.astimezone(BST).strftime("%H:%M BST"),
                                    "ticker": ticker,
                                    "rsi_at_signal": rsi,
                                    **m1, **outcomes,
                                })

            # Mode 2
            slice_daily_m2 = daily_full[daily_full.index.date < trade_day]
            if len(slice_daily_m2) >= 20:
                m2 = score_levels_at(slice_daily_m2)
                if m2:
                    outcomes = measure_outcome_m2(
                        daily_full, trade_day, m2["entry_price"], m2.get("stop_loss")
                    )
                    rsi = get_rsi_at_date(ticker, trade_day)
                    signals.append({
                        "date": trade_day.isoformat(),
                        "scan_time": "14:30 BST",
                        "ticker": ticker,
                        "rsi_at_signal": rsi,
                        **m2, **outcomes,
                    })

    except Exception:
        pass
    return signals


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("=" * 60)
    print("GarAI Intraday Scanner — Local Backtest")
    print("=" * 60)

    if not os.path.exists(DATA_ROOT):
        print(f"\nERROR: {DATA_ROOT} not found.")
        print("Run download_eodhd.py first.")
        return

    tickers = load_tickers()
    trade_days = [d.date() for d in pd.bdate_range(
        start=date.today()-timedelta(days=LOOKBACK_DAYS),
        end=date.today()-timedelta(days=1)
    )]

    print(f"Trading days to replay: {len(trade_days)}")
    print(f"({trade_days[0]} to {trade_days[-1]})")
    print(f"\nProcessing locally (no internet needed)...")

    all_signals = []
    for i, ticker in enumerate(tickers):
        sigs = process_ticker(ticker, trade_days)
        all_signals.extend(sigs)
        if (i+1) % 100 == 0:
            print(f"  {i+1}/{len(tickers)} tickers — {len(all_signals)} signals")

    if not all_signals:
        print("\nNo signals found.")
        return

    df = pd.DataFrame(all_signals)

    # Add market regime context
    try:
        from market_context import add_market_context, print_regime_summary
        df = add_market_context(df)
        has_context = True
    except ImportError:
        print("market_context.py not found — skipping regime analysis")
        has_context = False

    # Save results
    results_path = os.path.join(OUTPUT_DIR, "backtest_results.csv")
    try:
        df.to_csv(results_path, index=False, encoding="utf-8")
    except PermissionError:
        results_path = os.path.join(OUTPUT_DIR, "backtest_results_new.csv")
        df.to_csv(results_path, index=False, encoding="utf-8")
        print(f"Note: main CSV open — saved to backtest_results_new.csv")

    print(f"\nSaved {len(df)} signals to {results_path}")

    # Build summary
    lines = []
    lines.append("=" * 60)
    lines.append("GarAI Intraday Scanner - Local Backtest Summary")
    lines.append(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Lookback: {LOOKBACK_DAYS} days  |  Tickers: {len(tickers)}")
    lines.append(f"Total signals: {len(df)}")
    lines.append("=" * 60)

    for mode in ["MODE1_MOMENTUM", "SUPPORT_BOUNCE", "RESISTANCE_WARNING"]:
        sub = df[df["mode"] == mode]
        if sub.empty:
            continue
        lines.append(f"\n{'─'*40}")
        lines.append(f"  {mode}  ({len(sub)} signals)")
        lines.append(f"{'─'*40}")

        if mode == "MODE1_MOMENTUM":
            for h in OUTCOME_HOURS:
                col = f"return_{h}h_pct"
                if col in sub.columns:
                    valid = sub[col].dropna()
                    if not valid.empty:
                        lines.append(
                            f"  {h}hr: avg {valid.mean():+.2f}%  |  "
                            f"win {(valid>0).sum()/len(valid)*100:.0f}%  |  "
                            f"best {valid.max():+.2f}%  |  worst {valid.min():+.2f}%"
                        )
            if "max_gain_session_pct" in sub.columns:
                mg = sub["max_gain_session_pct"].dropna()
                if not mg.empty:
                    lines.append(
                        f"  Max session: avg {mg.mean():+.2f}%  |  "
                        f">5% in {(mg>5).sum()} signals  |  "
                        f">10% in {(mg>10).sum()} signals"
                    )
            # RSI analysis
            if "rsi_at_signal" in sub.columns:
                lines.append(f"\n  RSI at signal time breakdown (1hr return):")
                for lo, hi in [(0,30),(30,50),(50,70),(70,100)]:
                    band = sub[(sub["rsi_at_signal"]>=lo)&(sub["rsi_at_signal"]<hi)]
                    col = "return_1h_pct"
                    if not band.empty and col in band.columns:
                        valid = band[col].dropna()
                        if not valid.empty:
                            lines.append(
                                f"    RSI {lo}-{hi}: {len(band)} signals  |  "
                                f"avg {valid.mean():+.2f}%  |  "
                                f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                            )

        elif mode == "SUPPORT_BOUNCE":
            for d in MODE2_DAYS:
                col = f"return_{d}d_pct"
                if col in sub.columns:
                    valid = sub[col].dropna()
                    if not valid.empty:
                        sc = sub.get(f"stop_hit_{d}d", pd.Series(dtype=bool)).dropna()
                        stop_str = f"  |  stop hit {sc.mean()*100:.0f}%" if not sc.empty else ""
                        lines.append(
                            f"  {d}d: avg {valid.mean():+.2f}%  |  "
                            f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                            f"{stop_str}"
                        )

        # Market regime breakdown
        if has_context and "market_regime" in sub.columns:
            lines.append(f"\n  By market regime (3d return):")
            outcome_col = "return_1h_pct" if mode == "MODE1_MOMENTUM" else "return_3d_pct"
            if outcome_col in sub.columns:
                for regime in sorted(sub["market_regime"].unique()):
                    band = sub[sub["market_regime"]==regime]
                    valid = band[outcome_col].dropna()
                    if not valid.empty:
                        lines.append(
                            f"    {regime:12s}: {len(band):4d} signals  |  "
                            f"avg {valid.mean():+.2f}%  |  "
                            f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                        )

    lines.append(f"\n{'='*60}\n")
    summary = "\n".join(lines)
    print("\n" + summary)

    summary_path = os.path.join(OUTPUT_DIR, "backtest_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"Summary saved to {summary_path}")

    if has_context:
        print("\nRegime analysis:")
        print_regime_summary(df, "return_3d_pct", "SUPPORT_BOUNCE")


if __name__ == "__main__":
    run_backtest()
