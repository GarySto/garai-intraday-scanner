"""
GarAI — Local Data Downloader
==============================
Run this ONCE to build your local data store on D drive.
After this, backtests read from local files — no rate limits,
no internet dependency, runs in minutes not hours.

Also downloads premarket gap data for the premarket scanner backtest.

Usage:
  py download_data.py

Runtime: 3-6 hours for 4,000 tickers (run overnight)
Storage: ~3 GB on D drive

What it downloads:
  D:\\GarAI\\data\\daily\\       — 2 years daily OHLCV (all tickers)
  D:\\GarAI\\data\\intraday\\    — 60 days 5-min candles (all tickers)
  D:\\GarAI\\data\\premarket\\   — 60 days premarket data (all tickers)

Progress is saved as it goes — if it gets interrupted,
re-run and it will skip already-downloaded tickers.
"""

import yfinance as yf
import pandas as pd
import os
import time
import random
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

DATA_ROOT      = r"D:\GarAI\data"
DAILY_DIR      = os.path.join(DATA_ROOT, "daily")
INTRADAY_DIR   = os.path.join(DATA_ROOT, "intraday")
PREMARKET_DIR  = os.path.join(DATA_ROOT, "premarket")
TICKERS_FILE   = "tickers.txt"          # your clean tickers list
LOG_FILE       = os.path.join(DATA_ROOT, "download_log.txt")

BATCH_SIZE     = 10     # tickers per yf.download() call
SLEEP_MIN      = 4      # seconds between batches (min)
SLEEP_MAX      = 8      # seconds between batches (max) — random to avoid bot detection

# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_dirs():
    for d in [DATA_ROOT, DAILY_DIR, INTRADAY_DIR, PREMARKET_DIR]:
        os.makedirs(d, exist_ok=True)
    print(f"Data folders ready at {DATA_ROOT}")


def load_tickers():
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]
    raise FileNotFoundError(
        f"Cannot find {TICKERS_FILE}. "
        "Run this from your garai-intraday-scanner folder."
    )


def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def already_downloaded(ticker, data_dir, suffix=""):
    fname = f"{ticker}{suffix}.csv"
    path  = os.path.join(data_dir, fname)
    return os.path.exists(path) and os.path.getsize(path) > 200


# ── Download helpers ──────────────────────────────────────────────────────────

def download_batch_daily(batch):
    """2 years of daily OHLCV — used by both scanners."""
    try:
        data = yf.download(
            batch, period="2y", interval="1d",
            auto_adjust=True, progress=False, threads=False
        )
        if data.empty:
            return 0
        saved = 0
        close = data["Close"] if "Close" in data.columns else pd.DataFrame()
        if close.empty:
            return 0

        for t in batch:
            if already_downloaded(t, DAILY_DIR):
                saved += 1
                continue
            # Single ticker returns Series, multi returns DataFrame column
            if len(batch) == 1:
                df = data.copy()
            else:
                if t not in close.columns:
                    continue
                # Rebuild single-ticker df from multi-ticker download
                df = pd.DataFrame({
                    "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                    "High":   data["High"][t]   if "High"   in data.columns else None,
                    "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                    "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                    "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                })
            df = df.dropna(how="all")
            if len(df) < 10:
                continue
            df.to_csv(os.path.join(DAILY_DIR, f"{t}.csv"))
            saved += 1
        return saved
    except Exception as e:
        log(f"  Daily batch error: {str(e)[:80]}")
        return 0


def download_batch_intraday(batch):
    """60 days of 5-minute candles — intraday scanner."""
    try:
        data = yf.download(
            batch, period="60d", interval="5m",
            auto_adjust=True, progress=False, threads=False
        )
        if data.empty:
            return 0
        saved = 0
        close = data["Close"] if "Close" in data.columns else pd.DataFrame()

        for t in batch:
            if already_downloaded(t, INTRADAY_DIR, "_5m"):
                saved += 1
                continue
            if len(batch) == 1:
                df = data.copy()
            else:
                if hasattr(close, 'columns') and t not in close.columns:
                    continue
                df = pd.DataFrame({
                    "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                    "High":   data["High"][t]   if "High"   in data.columns else None,
                    "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                    "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                    "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                })
            df = df.dropna(how="all")
            if len(df) < 10:
                continue
            df.to_csv(os.path.join(INTRADAY_DIR, f"{t}_5m.csv"))
            saved += 1
        return saved
    except Exception as e:
        log(f"  Intraday batch error: {str(e)[:80]}")
        return 0


def download_batch_premarket(batch):
    """
    Premarket gap data — premarket scanner backtest.
    yfinance doesn't have a direct premarket history endpoint,
    so we use 1-minute data for the pre-market window and
    save it alongside daily data for gap calculation.
    We store daily data with the previous close so gap % can be calculated.
    The daily file already has this — premarket folder stores the
    extended hours data where available.
    """
    try:
        # Use 1m data with extended hours for premarket gap capture
        data = yf.download(
            batch, period="30d", interval="1m",
            auto_adjust=True, progress=False,
            threads=False, prepost=True  # includes pre/post market
        )
        if data.empty:
            return 0
        saved = 0
        close = data["Close"] if "Close" in data.columns else pd.DataFrame()

        for t in batch:
            if already_downloaded(t, PREMARKET_DIR, "_pre"):
                saved += 1
                continue
            if len(batch) == 1:
                df = data.copy()
            else:
                if hasattr(close, 'columns') and t not in close.columns:
                    continue
                df = pd.DataFrame({
                    "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                    "High":   data["High"][t]   if "High"   in data.columns else None,
                    "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                    "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                    "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                })
            df = df.dropna(how="all")
            if len(df) < 5:
                continue
            df.to_csv(os.path.join(PREMARKET_DIR, f"{t}_pre.csv"))
            saved += 1
        return saved
    except Exception as e:
        log(f"  Premarket batch error: {str(e)[:80]}")
        return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def run_phase(name, tickers, fn, data_dir, suffix=""):
    """Run one download phase with progress tracking."""
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")

    # Skip already-downloaded
    todo = [t for t in tickers if not already_downloaded(t, data_dir, suffix)]
    done_already = len(tickers) - len(todo)
    if done_already:
        print(f"Skipping {done_already} already downloaded. {len(todo)} remaining.")
    if not todo:
        print("All done — nothing to download.")
        return

    batches = [todo[i:i+BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    total_saved = done_already
    start = time.time()

    for i, batch in enumerate(batches):
        saved = fn(batch)
        total_saved += saved

        if (i + 1) % 10 == 0:
            elapsed  = time.time() - start
            rate     = (i + 1) / elapsed * BATCH_SIZE
            eta_secs = (len(todo) - (i+1)*BATCH_SIZE) / max(rate, 1)
            eta_mins = int(eta_secs / 60)
            pct = total_saved / len(tickers) * 100
            print(f"  Batch {i+1}/{len(batches)} — "
                  f"{total_saved}/{len(tickers)} ({pct:.0f}%) — "
                  f"ETA {eta_mins} mins")
            log(f"{name}: {total_saved}/{len(tickers)} complete")

        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    log(f"{name}: COMPLETE — {total_saved}/{len(tickers)} saved")
    print(f"\n{name} complete: {total_saved}/{len(tickers)} tickers saved")


def run():
    print("=" * 60)
    print("GarAI — Local Data Downloader")
    print("=" * 60)
    print(f"\nData will be saved to: {DATA_ROOT}")
    print("This runs overnight — leave it going and come back tomorrow.")
    print("Progress is saved as it goes. Safe to interrupt and re-run.\n")

    setup_dirs()
    tickers = load_tickers()
    print(f"Loaded {len(tickers)} tickers from {TICKERS_FILE}")

    log("=== Download session started ===")
    log(f"Tickers: {len(tickers)}")

    # Phase 1: Daily data (both scanners need this)
    run_phase(
        "Phase 1/3 — Daily OHLCV (2 years)",
        tickers, download_batch_daily, DAILY_DIR
    )

    # Phase 2: Intraday 5-min (intraday scanner backtest)
    run_phase(
        "Phase 2/3 — Intraday 5-min candles (60 days)",
        tickers, download_batch_intraday, INTRADAY_DIR, "_5m"
    )

    # Phase 3: Premarket extended hours (premarket scanner backtest)
    run_phase(
        "Phase 3/3 — Premarket extended hours (30 days)",
        tickers, download_batch_premarket, PREMARKET_DIR, "_pre"
    )

    print(f"\n{'='*60}")
    print("All downloads complete.")
    print(f"Data stored at: {DATA_ROOT}")
    print("\nNext steps:")
    print("  1. Run update_data.py to set up the weekly auto-refresh")
    print("  2. Run backtest.py to test with your full local dataset")
    print(f"{'='*60}\n")
    log("=== Download session complete ===")


if __name__ == "__main__":
    run()
