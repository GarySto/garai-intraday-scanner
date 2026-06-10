"""
GarAI — Daily Update Script
=============================
Runs every weekday at 21:30 BST via Windows Task Scheduler.
Five jobs in one script:

  1. T212 API  — refresh tickers.txt with current tradeable instruments
  2. yfinance  — append yesterday's daily candle to all D drive files
  3. yfinance  — append yesterday's 5-min intraday candles
  4. yfinance  — append yesterday's premarket (extended hours) candles
  5. T212 API  — pull order history, match to scanner output, log to trades.csv

Auth: T212 uses HTTP Basic Auth — base64(API_KEY:API_SECRET).
  Keys are stored as environment variables ONLY. Never hardcoded here.
  For GitHub Actions: stored as T212_API_KEY and T212_API_SECRET secrets.
  For local use: set via Windows environment variables or a .env file.

No bulk downloads. No rate limiting. Each ticker gets one tiny request.
Safe to run manually anytime — gaps are auto-detected and backfilled.

Usage:
  py daily_update.py              — run all jobs
  py daily_update.py --tickers    — refresh tickers only
  py daily_update.py --prices     — update price data only
  py daily_update.py --trades     — sync trade log only
  py daily_update.py --install    — run all jobs AND install Task Scheduler entry
"""

import os
import sys
import time
import base64
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz

# ── Config ────────────────────────────────────────────────────────────────────

# T212 API keys — from environment variables ONLY.
# Set via: Windows System Properties → Environment Variables
# Or for a single session: set T212_API_KEY=your_key in Command Prompt
T212_API_KEY    = os.environ.get("T212_API_KEY", "")
T212_API_SECRET = os.environ.get("T212_API_SECRET", "")

DATA_ROOT     = r"D:\GarAI\data"
DAILY_DIR     = os.path.join(DATA_ROOT, "daily")
INTRADAY_DIR  = os.path.join(DATA_ROOT, "intraday")
PREMARKET_DIR = os.path.join(DATA_ROOT, "premarket")
TICKERS_FILE  = "tickers.txt"
TRADES_FILE   = "trades.csv"
LOG_FILE      = os.path.join(DATA_ROOT, "daily_update_log.txt")

# Scanner output files to match trades against
INTRADAY_CSV = os.path.join("output", "intraday.csv")
UNIVERSE_CSV = os.path.join("..", "market-universe-generator", "output", "universe.csv")

T212_BASE  = "https://live.trading212.com/api/v0"
SLEEP      = 0.15   # between yfinance calls — small batches, no rate limits
BATCH_SIZE = 50     # tickers per yfinance batch

BST = pytz.timezone("Europe/London")


# ── T212 auth ─────────────────────────────────────────────────────────────────

def _t212_auth_header():
    """
    Build T212 Basic Auth header — used consistently in every T212 API call.

    T212 requires: Authorization: Basic base64(API_KEY:API_SECRET)
    Both keys must be set as environment variables. If either is missing,
    T212 jobs are skipped gracefully with a clear message.
    """
    if T212_API_KEY and T212_API_SECRET:
        credentials = base64.b64encode(
            f"{T212_API_KEY}:{T212_API_SECRET}".encode()
        ).decode()
        return {"Authorization": f"Basic {credentials}"}
    elif T212_API_KEY:
        # Legacy fallback — key alone (pre-secret T212 accounts)
        log("  WARNING: T212_API_SECRET not set — trying key-only auth")
        return {"Authorization": T212_API_KEY}
    return {}


def _t212_keys_available():
    """Return True if at least the API key is set."""
    if not T212_API_KEY:
        log("  T212_API_KEY not set — skipping T212 job")
        log("  Set it via: Windows Environment Variables → T212_API_KEY")
        return False
    return True


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    ts   = datetime.now(BST).strftime("%Y-%m-%d %H:%M BST")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(DATA_ROOT, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Job 1: Refresh tickers from T212 API ─────────────────────────────────────

def refresh_tickers():
    """
    Pull current ISA-tradeable instruments from T212 and update tickers.txt.

    WHY: tickers.txt is the source of truth for the scanner universe.
    T212 occasionally adds/removes instruments — keeping this fresh means
    the scanner never tries to price a delisted or non-ISA stock.
    """
    print("\n" + "=" * 50)
    print("Job 1: Refresh tickers from T212 API")
    print("=" * 50)

    if not _t212_keys_available():
        return False

    headers = _t212_auth_header()
    url     = f"{T212_BASE}/equity/metadata/instruments"

    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            log("  T212 rate limit hit — try again in 60 seconds")
            return False
        if r.status_code == 401:
            log("  T212 auth failed (401) — check T212_API_KEY and T212_API_SECRET")
            return False
        if r.status_code != 200:
            log(f"  T212 API error: {r.status_code} — {r.text[:200]}")
            return False

        instruments = r.json()
        if not instruments:
            log("  No instruments returned from T212")
            return False

        # Extract US stocks only
        # T212 format: "AAPL_US_EQ" → clean to "AAPL"
        tickers = []
        for inst in instruments:
            raw = inst.get("ticker", "")
            if "_US_EQ" in raw:
                clean = raw.replace("_US_EQ", "")
            elif "_" not in raw and raw.isupper() and len(raw) <= 6:
                clean = raw
            else:
                continue
            if clean and clean.isalpha():
                tickers.append(clean)

        tickers = sorted(set(tickers))

        with open(TICKERS_FILE, "w") as f:
            f.write("\n".join(tickers))

        log(f"  Tickers refreshed: {len(tickers)} US instruments saved to {TICKERS_FILE}")
        return True

    except Exception as e:
        log(f"  T212 ticker refresh error: {e}")
        return False


# ── Job 2-4: Update price data ────────────────────────────────────────────────

def get_last_date_in_file(path):
    """Read the last date in a CSV file."""
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        return df.index[-1].date()
    except Exception:
        return None


def append_new_rows(path, new_df):
    """
    Append only genuinely new rows to an existing CSV.
    Skips rows already present — safe to run multiple times.
    Returns True if new rows were written, False if already up to date.
    """
    try:
        if not os.path.exists(path):
            new_df.to_csv(path)
            return True

        existing = pd.read_csv(path, index_col=0, parse_dates=True)
        if existing.empty:
            new_df.to_csv(path)
            return True

        last_date = existing.index[-1]
        new_rows  = new_df[new_df.index > last_date]

        if new_rows.empty:
            return False  # already up to date

        combined = pd.concat([existing, new_rows])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        combined.to_csv(path)
        return True
    except Exception:
        return False


def update_daily_prices(tickers):
    """
    Fetch last 5 days of daily OHLCV and append new candles to D drive files.
    Only updates tickers that already have a CSV — does not create new ones.
    """
    print("\n" + "=" * 50)
    print("Job 2: Update daily prices")
    print("=" * 50)

    updated = 0
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            batch_with_files = [
                t for t in batch
                if os.path.exists(os.path.join(DAILY_DIR, f"{t}.csv"))
            ]
            if not batch_with_files:
                continue

            data = yf.download(
                batch_with_files, period="5d", interval="1d",
                auto_adjust=True, progress=False, threads=False
            )
            if data.empty:
                continue

            for t in batch_with_files:
                path = os.path.join(DAILY_DIR, f"{t}.csv")
                if len(batch_with_files) == 1:
                    new_df = data.copy()
                else:
                    new_df = pd.DataFrame({
                        "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                        "High":   data["High"][t]   if "High"   in data.columns else None,
                        "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                        "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                        "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                    })
                new_df = new_df.dropna(how="all")
                if append_new_rows(path, new_df):
                    updated += 1

        except Exception:
            pass

        if (i + 1) % 10 == 0:
            print(f"  Daily: batch {i+1}/{len(batches)}, {updated} files updated")

        time.sleep(SLEEP)

    log(f"  Daily prices updated: {updated} files")
    return updated


def update_intraday_prices(tickers):
    """Fetch yesterday's 5-min candles and append to intraday files."""
    print("\n" + "=" * 50)
    print("Job 3: Update intraday 5-min candles")
    print("=" * 50)

    updated = 0
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            batch_with_files = [
                t for t in batch
                if os.path.exists(os.path.join(INTRADAY_DIR, f"{t}_5m.csv"))
            ]
            if not batch_with_files:
                continue

            data = yf.download(
                batch_with_files, period="2d", interval="5m",
                auto_adjust=True, progress=False, threads=False
            )
            if data.empty:
                continue

            for t in batch_with_files:
                path = os.path.join(INTRADAY_DIR, f"{t}_5m.csv")
                if len(batch_with_files) == 1:
                    new_df = data.copy()
                else:
                    new_df = pd.DataFrame({
                        "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                        "High":   data["High"][t]   if "High"   in data.columns else None,
                        "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                        "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                        "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                    })
                new_df = new_df.dropna(how="all")
                if append_new_rows(path, new_df):
                    updated += 1

        except Exception:
            pass

        if (i + 1) % 10 == 0:
            print(f"  Intraday: batch {i+1}/{len(batches)}, {updated} files updated")

        time.sleep(SLEEP)

    log(f"  Intraday prices updated: {updated} files")
    return updated


def update_premarket(tickers):
    """
    Fetch yesterday's premarket (extended hours) candles and append.
    Uses prepost=True to include pre/post market data.
    Stores in D:/GarAI/data/premarket/ as {TICKER}_pre.csv.
    """
    print("\n" + "=" * 50)
    print("Job 4: Update premarket candles")
    print("=" * 50)

    os.makedirs(PREMARKET_DIR, exist_ok=True)
    updated = 0
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            data = yf.download(
                batch, period="2d", interval="1m",
                auto_adjust=True, progress=False,
                threads=False, prepost=True
            )
            if data.empty:
                continue

            for t in batch:
                path = os.path.join(PREMARKET_DIR, f"{t}_pre.csv")
                if len(batch) == 1:
                    new_df = data.copy()
                else:
                    new_df = pd.DataFrame({
                        "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                        "High":   data["High"][t]   if "High"   in data.columns else None,
                        "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                        "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                        "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                    })
                new_df = new_df.dropna(how="all")
                if append_new_rows(path, new_df):
                    updated += 1

        except Exception:
            pass

        if (i + 1) % 10 == 0:
            print(f"  Premarket: batch {i+1}/{len(batches)}, {updated} files updated")

        time.sleep(SLEEP)

    log(f"  Premarket data updated: {updated} files")
    return updated


# ── Job 5: Sync trade log from T212 ──────────────────────────────────────────

def sync_trade_log():
    """
    Pull order history from T212 API.
    Match each fill against scanner output to determine if it was scanner-driven.
    Calculate outcome (entry vs current price).
    Append new trades to trades.csv — skips any order IDs already recorded.
    """
    print("\n" + "=" * 50)
    print("Job 5: Sync trade log from T212")
    print("=" * 50)

    if not _t212_keys_available():
        return

    headers = _t212_auth_header()

    try:
        r = requests.get(
            f"{T212_BASE}/equity/history/orders",
            headers=headers,
            params={"limit": 50},
            timeout=30
        )
        if r.status_code == 429:
            log("  T212 rate limit — try again in 60 seconds")
            return
        if r.status_code == 401:
            log("  T212 auth failed (401) — check T212_API_KEY and T212_API_SECRET")
            return
        if r.status_code != 200:
            log(f"  T212 orders error: {r.status_code}")
            return

        orders = r.json().get("items", [])
        if not orders:
            log("  No orders found in T212 history")
            return

    except Exception as e:
        log(f"  T212 order fetch error: {e}")
        return

    # Load scanner outputs to match against
    scanner_candidates = set()
    for csv_path in [INTRADAY_CSV, UNIVERSE_CSV]:
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                if "ticker" in df.columns:
                    scanner_candidates.update(df["ticker"].dropna().tolist())
            except Exception:
                pass

    # Load existing trades to avoid duplicates
    existing_ids = set()
    if os.path.exists(TRADES_FILE):
        try:
            existing    = pd.read_csv(TRADES_FILE)
            if "order_id" in existing.columns:
                existing_ids = set(existing["order_id"].astype(str).tolist())
        except Exception:
            pass

    # Process each order
    new_trades = []
    for order in orders:
        order_id = str(order.get("id", ""))
        if order_id in existing_ids:
            continue

        status = order.get("status", "")
        if status not in ["FILLED", "PARTIALLY_FILLED"]:
            continue

        ticker     = order.get("ticker", "").replace("_US_EQ", "")
        direction  = "BUY" if order.get("type") == "MARKET" else order.get("type", "")
        filled_qty = order.get("filledQuantity", 0)
        filled_at  = order.get("fillPrice", None)
        date_str   = order.get("dateCreated", "")[:10]

        scanner_driven = ticker in scanner_candidates

        # Get current price for unrealised P&L
        current_price = None
        try:
            tk   = yf.Ticker(ticker)
            hist = tk.history(period="1d")
            if not hist.empty:
                current_price = round(hist["Close"].iloc[-1], 4)
        except Exception:
            pass

        outcome_pct = None
        if filled_at and current_price:
            outcome_pct = round((current_price - filled_at) / filled_at * 100, 2)

        new_trades.append({
            "order_id":       order_id,
            "date":           date_str,
            "ticker":         ticker,
            "direction":      direction,
            "quantity":       filled_qty,
            "entry_price":    filled_at,
            "current_price":  current_price,
            "outcome_pct":    outcome_pct,
            "scanner_driven": scanner_driven,
            "status":         status,
        })

    if not new_trades:
        log("  Trade log already up to date — no new fills")
        return

    new_df = pd.DataFrame(new_trades)
    if os.path.exists(TRADES_FILE):
        existing = pd.read_csv(TRADES_FILE)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(TRADES_FILE, index=False)
    log(f"  Trade log updated: {len(new_trades)} new fills added to {TRADES_FILE}")

    for t in new_trades:
        outcome_str  = f" → {t['outcome_pct']:+.2f}%" if t["outcome_pct"] else ""
        scanner_str  = " [scanner]" if t["scanner_driven"] else " [manual]"
        print(f"  {t['date']} {t['ticker']} {t['direction']} "
              f"@ ${t['entry_price']}{outcome_str}{scanner_str}")


# ── Task Scheduler install ────────────────────────────────────────────────────

def install_task():
    """
    Install this script as a daily Task Scheduler job at 21:30 BST.
    Run with: py daily_update.py --install
    Requires Administrator privileges.
    """
    import subprocess
    script = os.path.abspath(__file__)
    python = sys.executable

    cmd = [
        "schtasks", "/create",
        "/tn", "GarAI_Daily_Update",
        "/tr", f'"{python}" "{script}"',
        "/sc", "DAILY",
        "/st", "21:30",
        "/ru", "SYSTEM",
        "/f"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("\nTask installed — daily_update.py will run every day at 21:30.")
            print("PC must be on at 21:30 BST for it to run.")
            print("If you miss a day, run manually: py daily_update.py")
            print("Gaps are auto-detected and backfilled on next run.")
        else:
            print(f"\nTask install failed: {result.stderr}")
            print("Try running Command Prompt as Administrator.")
    except Exception as e:
        print(f"\nError: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def load_tickers():
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]
    return []


def run():
    print("=" * 60)
    print("GarAI — Daily Update")
    print(f"Run: {datetime.now(BST).strftime('%A %d %b %Y %H:%M BST')}")
    print("=" * 60)

    # Quick key check at startup — warn early rather than fail silently per job
    if not T212_API_KEY:
        print("\nWARNING: T212_API_KEY environment variable not set.")
        print("T212 jobs (tickers refresh + trade sync) will be skipped.")
        print("Set via: Windows System Properties → Advanced → Environment Variables")
    elif not T212_API_SECRET:
        print("\nWARNING: T212_API_SECRET not set — will try key-only auth.")

    args = sys.argv[1:]

    run_tickers = "--tickers" in args or not args
    run_prices  = "--prices"  in args or not args
    run_trades  = "--trades"  in args or not args

    log("=== Daily update started ===")

    if run_tickers:
        refresh_tickers()

    tickers = load_tickers()
    if not tickers:
        log("No tickers loaded — check tickers.txt")
        return

    print(f"\nLoaded {len(tickers)} tickers")

    if run_prices and os.path.exists(DATA_ROOT):
        update_daily_prices(tickers)
        update_intraday_prices(tickers)
        update_premarket(tickers)
    elif run_prices:
        log(f"D drive not found at {DATA_ROOT} — skipping price update")
        log("Run download_eodhd.py first to build the initial dataset")

    if run_trades:
        sync_trade_log()

    print(f"\n{'=' * 60}")
    print("Daily update complete.")
    log("=== Daily update complete ===")


if __name__ == "__main__":
    if "--install" in sys.argv:
        run()
        install_task()
    else:
        run()
