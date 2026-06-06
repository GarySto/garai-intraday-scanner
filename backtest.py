"""
GarAI Intraday Scanner — Local Backtest
========================================
Replays the intraday scanner historically, 30 minutes at a time,
using only data that would have been visible at each point in time.
No lookahead bias. Parallel data fetching for speed.

Run from your garai-intraday-scanner folder:
  py backtest.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import os
import warnings
warnings.filterwarnings("ignore")

# ── Configuration ─────────────────────────────────────────────────────────────

TICKERS_FILE    = "tickers.txt"
OUTPUT_DIR      = "."
LOOKBACK_DAYS   = 50        # yfinance 5-min limit is ~60 days
MAX_TICKERS     = 1500      # 1500 = good balance of coverage vs run time (~15 mins)
MAX_WORKERS     = 15        # parallel threads — 10 is safe for yfinance rate limits

# Mode 1 thresholds
MOMENTUM_MIN_PCT = 5.0
RVOL_MIN         = 5.0

# Mode 2 thresholds
LEVEL_BAND_PCT   = 0.015
MIN_TOUCHES      = 3
NEAR_LEVEL_PCT   = 0.03
ATR_PERIOD       = 14
ATR_STOP_MULT    = 1.0
MODE1_START_BST  = 14             # earliest BST hour for Mode 1
MODE1_END_BST    = 19             # cutoff — win rate collapses after 19:00 BST
MODE2_TOUCH_EXACT = 4             # only flag levels with exactly 4 touches

# Outcome windows
OUTCOME_HOURS    = [1, 2, 4]
MODE2_DAYS       = [1, 3, 5]

BST = pytz.timezone("Europe/London")
UTC = pytz.utc

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_tickers(path):
    for p in [path, os.path.join("..", path)]:
        if os.path.exists(p):
            with open(p) as f:
                return [l.strip() for l in f if l.strip()][:MAX_TICKERS]
    raise FileNotFoundError(f"Cannot find {path}. Run from garai-intraday-scanner folder.")


def calc_atr(hist, period=ATR_PERIOD):
    high  = hist["High"]
    low   = hist["Low"]
    close = hist["Close"].shift(1)
    tr = pd.concat([(high-low), (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return None if np.isnan(val) else val


def find_levels(hist):
    prices = pd.concat([hist["High"], hist["Low"]]).dropna().values
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
            level_price = float(np.median(cluster))
            levels.append({
                "price":           round(level_price, 4),
                "touches":         int(mask.sum()),
                "lowest_at_level": round(float(cluster.min()), 4),
                "level_type":      "support" if level_price < current else "resistance",
            })
            used[mask] = True
    return levels


def score_momentum_at(intraday_slice, hist_daily, scan_hour=15):
    try:
        if intraday_slice is None or len(intraday_slice) < 6:
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
        # Time window filter — win rate collapses after 19:00 BST
        if not (MODE1_START_BST <= scan_hour < MODE1_END_BST):
            return None
        # Acceleration signal removed — backtest showed it hurts win rate
        total    = round(min(pct_from_open/10*5,5) + min((rvol-1)/3*5,5), 2)
        return {
            "mode": "MODE1_MOMENTUM", "score": total,
            "pct_from_open": round(pct_from_open,2), "rvol": round(rvol,2),
            "entry_price": round(current,4),
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
            total = round((1-dist_pct/NEAR_LEVEL_PCT)*5 + min((lv["touches"]-1)*1.5,4), 2)
            if total <= best_score:
                continue
            best_score = total
            best = {
                "mode":          "SUPPORT_BOUNCE" if lv["level_type"]=="support" else "RESISTANCE_WARNING",
                "score":         total,
                "level_price":   lv["price"],
                "level_touches": lv["touches"],
                "level_type":    lv["level_type"],
                "dist_pct":      round(dist_pct*100,2),
                "atr":           round(atr,2),
                "stop_loss":     round(lv["lowest_at_level"]-(ATR_STOP_MULT*atr),4),
                "entry_price":   round(current,4),
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
                outcomes[f"return_{h}h_pct"]   = round((ep-entry_price)/entry_price*100,2)
                outcomes[f"max_gain_{h}h_pct"] = round((w["High"].max()-entry_price)/entry_price*100,2)
                outcomes[f"stop_hit_{h}h"]     = bool(w["Low"].min() < entry_price*0.97)
        outcomes["return_eod_pct"]         = round((future["Close"].iloc[-1]-entry_price)/entry_price*100,2)
        outcomes["max_gain_session_pct"]   = round((future["High"].max()-entry_price)/entry_price*100,2)
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
                outcomes[f"return_{d}d_pct"]   = round((ep-entry_price)/entry_price*100,2)
                outcomes[f"max_gain_{d}d_pct"] = round((w["High"].max()-entry_price)/entry_price*100,2)
                if stop_price:
                    outcomes[f"stop_hit_{d}d"] = bool(w["Low"].min() < stop_price)
    except Exception:
        pass
    return outcomes


# ── Fetch one ticker's data ───────────────────────────────────────────────────

def fetch_ticker(ticker):
    """Fetch all data for one ticker. Returns (ticker, daily, intraday) or None."""
    try:
        tk = yf.Ticker(ticker)
        daily = tk.history(period="6mo", interval="1d", auto_adjust=True)
        if daily is None or len(daily) < 30:
            return None
        intraday = tk.history(
            period=f"{min(LOOKBACK_DAYS+5, 59)}d",
            interval="5m", auto_adjust=True
        )
        if intraday is None or intraday.empty:
            return None

        # Normalise timezones
        for df in [daily, intraday]:
            if df.index.tz is None:
                df.index = df.index.tz_localize(UTC)
            else:
                df.index = df.index.tz_convert(UTC)

        return (ticker, daily, intraday)
    except Exception:
        return None


# ── Process one ticker's signals ──────────────────────────────────────────────

def process_ticker(ticker, daily_full, intraday_full, trade_days):
    signals = []
    try:
        for trade_day in trade_days:
            session_start = datetime(trade_day.year, trade_day.month, trade_day.day,
                                     13, 30, tzinfo=UTC)
            session_end   = datetime(trade_day.year, trade_day.month, trade_day.day,
                                     20,  0, tzinfo=UTC)

            day_intraday = intraday_full[
                (intraday_full.index.date == trade_day) &
                (intraday_full.index >= session_start)
            ]

            # Mode 1 — replay 30-min intervals
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
                        m1 = score_momentum_at(sl, slice_daily, scan_time.astimezone(BST).hour)
                        if m1:
                            outcomes = measure_outcome_m1(day_intraday, scan_time, m1["entry_price"])
                            signals.append({
                                "date": trade_day.isoformat(),
                                "scan_time": scan_time.astimezone(BST).strftime("%H:%M BST"),
                                "ticker": ticker, **m1, **outcomes,
                            })

            # Mode 2 — once per day
            slice_daily_m2 = daily_full[daily_full.index.date < trade_day]
            if len(slice_daily_m2) >= 20:
                m2 = score_levels_at(slice_daily_m2)
                if m2:
                    outcomes = measure_outcome_m2(
                        daily_full, trade_day, m2["entry_price"], m2.get("stop_loss")
                    )
                    signals.append({
                        "date": trade_day.isoformat(),
                        "scan_time": "14:30 BST",
                        "ticker": ticker, **m2, **outcomes,
                    })
    except Exception:
        pass
    return signals


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("=" * 60)
    print("GarAI Intraday Scanner - Backtest")
    print("=" * 60)

    tickers    = load_tickers(TICKERS_FILE)
    trade_days = [d.date() for d in pd.bdate_range(
        start=date.today()-timedelta(days=LOOKBACK_DAYS),
        end=date.today()-timedelta(days=1)
    )]

    print(f"Tickers: {len(tickers)}  |  Trading days: {len(trade_days)}")
    print(f"Parallel workers: {MAX_WORKERS}")
    print(f"Fetching data (this is the slow part)...\n")

    # ── Phase 1: fetch all data in parallel ──
    fetched  = {}
    skipped  = 0
    done     = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                ticker, daily, intraday = result
                fetched[ticker] = (daily, intraday)
            else:
                skipped += 1
            if done % 50 == 0:
                print(f"  Fetched {done}/{len(tickers)} tickers ({skipped} skipped)...")

    print(f"\nData fetched: {len(fetched)} tickers usable, {skipped} skipped")
    print(f"Replaying signals...")

    # ── Phase 2: process signals (fast, no network) ──
    all_signals = []
    for i, (ticker, (daily, intraday)) in enumerate(fetched.items()):
        sigs = process_ticker(ticker, daily, intraday, trade_days)
        all_signals.extend(sigs)
        if (i+1) % 50 == 0:
            print(f"  Processed {i+1}/{len(fetched)} tickers, {len(all_signals)} signals...")

    if not all_signals:
        print("\nNo signals found. Try increasing MAX_TICKERS or LOOKBACK_DAYS.")
        return

    df = pd.DataFrame(all_signals)

    # ── Save CSV ──
    results_path = os.path.join(OUTPUT_DIR, "backtest_results.csv")
    try:
        df.to_csv(results_path, index=False, encoding="utf-8")
        print(f"\nSaved {len(df)} signals to {results_path}")
    except PermissionError:
        alt = os.path.join(OUTPUT_DIR, "backtest_results_new.csv")
        df.to_csv(alt, index=False, encoding="utf-8")
        print(f"\nNote: backtest_results.csv is open in Excel.")
        print(f"Saved to {alt} instead. Close Excel next time for the main file.")

    # ── Summary ──
    lines = []
    lines.append("=" * 60)
    lines.append("GarAI Intraday Scanner - Backtest Summary")
    lines.append(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Tickers: {len(tickers)}  |  Lookback: {LOOKBACK_DAYS} days")
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
            if "return_eod_pct" in sub.columns:
                eod = sub["return_eod_pct"].dropna()
                if not eod.empty:
                    lines.append(
                        f"  EOD: avg {eod.mean():+.2f}%  |  "
                        f"win {(eod>0).sum()/len(eod)*100:.0f}%"
                    )
            if "max_gain_session_pct" in sub.columns:
                mg = sub["max_gain_session_pct"].dropna()
                if not mg.empty:
                    lines.append(
                        f"  Max gain session: avg {mg.mean():+.2f}%  |  "
                        f">5% in {(mg>5).sum()} signals  |  "
                        f">10% in {(mg>10).sum()} signals"
                    )
            lines.append(f"\n  Score band breakdown (1hr return):")
            for lo, hi in [(0,4),(4,6),(6,8),(8,10)]:
                band = sub[(sub["score"]>=lo)&(sub["score"]<hi)]
                col  = "return_1h_pct"
                if not band.empty and col in band.columns:
                    valid = band[col].dropna()
                    if not valid.empty:
                        lines.append(
                            f"    Score {lo}-{hi}: {len(band)} signals  |  "
                            f"avg {valid.mean():+.2f}%  |  "
                            f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                        )
            # Acceleration breakdown
            if "accelerating" in sub.columns:
                lines.append(f"\n  Acceleration signal breakdown (1hr return):")
                for accel in [True, False]:
                    band = sub[sub["accelerating"]==accel]
                    col  = "return_1h_pct"
                    if not band.empty and col in band.columns:
                        valid = band[col].dropna()
                        if not valid.empty:
                            lines.append(
                                f"    Accelerating={accel}: {len(band)} signals  |  "
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
                        stop_str = f"  |  stop hit {sc.sum()/len(sc)*100:.0f}%" if not sc.empty else ""
                        lines.append(
                            f"  {d}d: avg {valid.mean():+.2f}%  |  "
                            f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                            f"{stop_str}"
                        )
            # Touch count breakdown
            if "level_touches" in sub.columns:
                lines.append(f"\n  Touch count breakdown (3d return):")
                for t_lo, t_hi in [(2,3),(3,5),(5,100)]:
                    band = sub[(sub["level_touches"]>=t_lo)&(sub["level_touches"]<t_hi)]
                    col  = "return_3d_pct"
                    if not band.empty and col in band.columns:
                        valid = band[col].dropna()
                        if not valid.empty:
                            label = f"{t_lo}+" if t_hi==100 else f"{t_lo}-{t_hi-1}"
                            lines.append(
                                f"    Touches {label}: {len(band)} signals  |  "
                                f"avg {valid.mean():+.2f}%  |  "
                                f"win {(valid>0).sum()/len(valid)*100:.0f}%"
                            )

        elif mode == "RESISTANCE_WARNING":
            lines.append("  (Correct = price fell after signal)")
            for d in MODE2_DAYS:
                col = f"return_{d}d_pct"
                if col in sub.columns:
                    valid = sub[col].dropna()
                    if not valid.empty:
                        lines.append(
                            f"  {d}d: avg {valid.mean():+.2f}%  |  "
                            f"correct (fell) {(valid<0).sum()/len(valid)*100:.0f}%"
                        )

    lines.append(f"\n{'='*60}")
    lines.append("Key questions answered:")
    lines.append("  1. Do higher Mode 1 scores produce better 1hr returns?")
    lines.append("     See score band breakdown above.")
    lines.append("  2. Does the acceleration signal add value?")
    lines.append("     See acceleration breakdown above.")
    lines.append("  3. Do more touches = better bounce rate?")
    lines.append("     See touch count breakdown above.")
    lines.append("  4. Is the ATR stop-loss calibrated sensibly?")
    lines.append("     See stop hit % in support bounce section.")
    lines.append(f"{'='*60}\n")

    summary = "\n".join(lines)
    print("\n" + summary)

    summary_path = os.path.join(OUTPUT_DIR, "backtest_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"Summary saved to {summary_path}")


if __name__ == "__main__":
    run_backtest()
