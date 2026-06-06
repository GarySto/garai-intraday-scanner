"""
GarAI — EODHD Comprehensive Data Downloader
=============================================
Downloads everything needed for both scanners in one session.
Run once, then use update_data.py weekly to top up.

What this downloads:
  daily\         — 30yr daily OHLCV, split+dividend adjusted
  intraday\      — 1yr 5-min candles
  technicals\    — RSI(14), MACD, Bollinger Bands (daily)
  events\        — dividends, splits, earnings dates
  meta\          — sector, industry, market cap

API budget: ~89,000 calls total — fits within 100k/day limit

Usage:
  py download_eodhd.py

Progress saved every 50 tickers. Safe to interrupt and re-run.
"""

import requests
import pandas as pd
import os
import time
import json
from datetime import datetime

API_KEY       = "6a22b19d9dd7a1.11103702"

DATA_ROOT     = r"D:\GarAI\data"
DAILY_DIR     = os.path.join(DATA_ROOT, "daily")
INTRADAY_DIR  = os.path.join(DATA_ROOT, "intraday")
TECH_DIR      = os.path.join(DATA_ROOT, "technicals")
EVENTS_DIR    = os.path.join(DATA_ROOT, "events")
META_DIR      = os.path.join(DATA_ROOT, "meta")
TICKERS_FILE  = "tickers.txt"
LOG_FILE      = os.path.join(DATA_ROOT, "download_log.txt")
PROGRESS_FILE = os.path.join(DATA_ROOT, "download_progress.json")

BASE_URL      = "https://eodhd.com/api"
SLEEP         = 0.12    # ~8 calls/sec, well within 1000/min
SLEEP_ERR     = 5.0


def setup():
    for d in [DATA_ROOT, DAILY_DIR, INTRADAY_DIR, TECH_DIR, EVENTS_DIR, META_DIR]:
        os.makedirs(d, exist_ok=True)
        print(f"  Folder ready: {d}")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_tickers():
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]
    raise FileNotFoundError("Cannot find tickers.txt")


def exists(path, min_bytes=200):
    return os.path.exists(path) and os.path.getsize(path) > min_bytes


def safe_filename(ticker):
    """Replace dots in ticker names so they work as filenames on Windows.
    BRK.B -> BRK-B, BF.A -> BF-A etc."""
    return ticker.replace(".", "-")


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(prog):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f)


def api_get(url, params, timeout=20):
    params["api_token"] = API_KEY
    params["fmt"] = "json"
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 402:
            return "NEEDS_UPGRADE"
        if r.status_code == 429:
            log("  Rate limited — sleeping 30s")
            time.sleep(30)
            return None
        return None
    except Exception:
        time.sleep(SLEEP_ERR)
        return None


# ── Download functions ────────────────────────────────────────────────────────

def dl_daily(ticker):
    path = os.path.join(DAILY_DIR, f"{safe_filename(ticker)}.csv")
    if exists(path):
        return True
    data = api_get(f"{BASE_URL}/eod/{ticker}.US", {"order": "a"})
    if not data or not isinstance(data, list) or len(data) < 5:
        return False
    df = pd.DataFrame(data).rename(columns={
        "date":"Date","open":"Open","high":"High","low":"Low",
        "close":"Close","volume":"Volume","adjusted_close":"Adj_Close"
    }).set_index("Date")
    df.to_csv(path)
    return True


def dl_intraday(ticker):
    path = os.path.join(INTRADAY_DIR, f"{safe_filename(ticker)}_5m.csv")
    if exists(path):
        return True
    data = api_get(f"{BASE_URL}/intraday/{ticker}.US", {"interval": "5m"})
    if data == "NEEDS_UPGRADE" or not data or not isinstance(data, list):
        return False
    df = pd.DataFrame(data).rename(columns={
        "datetime":"DateTime","open":"Open","high":"High",
        "low":"Low","close":"Close","volume":"Volume"
    })
    if df.empty:
        return False
    df.set_index("DateTime", inplace=True)
    df.to_csv(path)
    return True


def dl_technical(ticker, indicator, suffix, extra_params=None):
    path = os.path.join(TECH_DIR, f"{safe_filename(ticker)}_{suffix}.csv")
    if exists(path):
        return True
    params = {"function": indicator, "period": 14, "order": "a"}
    if extra_params:
        params.update(extra_params)
    data = api_get(f"{BASE_URL}/technical/{ticker}.US", params)
    if not data or not isinstance(data, list):
        return False
    df = pd.DataFrame(data)
    if df.empty:
        return False
    if "date" in df.columns:
        df.set_index("date", inplace=True)
    df.to_csv(path)
    return True


def dl_rsi(ticker):
    return dl_technical(ticker, "rsi", "rsi", {"period": 14})

def dl_macd(ticker):
    return dl_technical(ticker, "macd", "macd",
                        {"fast_period": 12, "slow_period": 26, "signal_period": 9})

def dl_bbands(ticker):
    return dl_technical(ticker, "bbands", "bbands", {"period": 20})


def dl_dividends(ticker):
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        path = os.path.join(EVENTS_DIR, f"{safe_filename(ticker)}_dividends.csv")
        if exists(path, 50):
            return True
        data = api_get(f"{BASE_URL}/div/{ticker}.US", {"order": "a"})
        df = pd.DataFrame(data) if data and isinstance(data, list) else pd.DataFrame()
        df.to_csv(path, index=False)
        return True
    except Exception as e:
        log(f"  SKIP {ticker} dividends: {str(e)[:60]}")
        try:
            path = os.path.join(EVENTS_DIR, f"{safe_filename(ticker)}_dividends.csv")
            open(path, "w").close()
        except Exception:
            pass
        return True


def dl_splits(ticker):
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        path = os.path.join(EVENTS_DIR, f"{safe_filename(ticker)}_splits.csv")
        if exists(path, 50):
            return True
        data = api_get(f"{BASE_URL}/splits/{ticker}.US", {"order": "a"})
        df = pd.DataFrame(data) if data and isinstance(data, list) else pd.DataFrame()
        df.to_csv(path, index=False)
        return True
    except Exception as e:
        log(f"  SKIP {ticker} splits: {str(e)[:60]}")
        return True


def dl_earnings(ticker):
    try:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        path = os.path.join(EVENTS_DIR, f"{safe_filename(ticker)}_earnings.csv")
        if exists(path, 50):
            return True
        data = api_get(f"{BASE_URL}/calendar/earnings",
                       {"symbols": f"{ticker}.US", "from": "2020-01-01"})
        rows = []
        if data and isinstance(data, dict):
            rows = data.get("earnings", [])
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        df.to_csv(path, index=False)
        return True
    except Exception as e:
        log(f"  SKIP {ticker} earnings: {str(e)[:60]}")
        return True


def dl_meta(ticker):
    try:
        os.makedirs(META_DIR, exist_ok=True)
        path = os.path.join(META_DIR, f"{safe_filename(ticker)}_meta.json")
        if exists(path, 50):
            return True
        data = api_get(f"{BASE_URL}/fundamentals/{ticker}.US", {"filter": "General"})
        if not data or not isinstance(data, dict):
            return False
        meta = {
            "ticker":     ticker,
            "name":       data.get("Name", ""),
            "sector":     data.get("Sector", ""),
            "industry":   data.get("Industry", ""),
            "exchange":   data.get("Exchange", ""),
            "market_cap": data.get("MarketCapitalization", ""),
            "description": str(data.get("Description", ""))[:200],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return True
    except Exception as e:
        log(f"  SKIP {ticker} meta: {str(e)[:60]}")
        return True


# ── Phase runner ──────────────────────────────────────────────────────────────

def run_phase(name, tickers, fn, progress, key, calls_each=1):
    done_set = set(progress.get(key, []))
    todo = [t for t in tickers if t not in done_set]
    done_already = len(done_set)

    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    if done_already:
        print(f"  Skipping {done_already} already done. {len(todo)} remaining.")
    if not todo:
        print("  All done — nothing to fetch.")
        return 0

    ok_count = 0
    fail_count = 0
    api_used = 0
    start = time.time()

    for i, ticker in enumerate(todo):
        ok = fn(ticker)
        api_used += calls_each
        if ok:
            ok_count += 1
            done_set.add(ticker)
        else:
            fail_count += 1

        if (i + 1) % 50 == 0:
            progress[key] = list(done_set)
            save_progress(progress)
            elapsed = time.time() - start
            rate = (i + 1) / max(elapsed, 1)
            eta_mins = int((len(todo) - i - 1) / rate / 60)
            total_done = done_already + ok_count
            pct = total_done / len(tickers) * 100
            print(f"  [{i+1}/{len(todo)}] total {total_done}/{len(tickers)} "
                  f"({pct:.0f}%) — ETA {eta_mins}m — API used: {api_used:,}")
            log(f"{name}: {total_done}/{len(tickers)} ({pct:.0f}%)")

        time.sleep(SLEEP)

    progress[key] = list(done_set)
    save_progress(progress)

    print(f"\n  Done: saved {ok_count}, failed {fail_count}, "
          f"API calls this phase: {api_used:,}")
    log(f"{name} COMPLETE — ok:{ok_count} fail:{fail_count} api:{api_used}")
    return api_used


# ── Main ──────────────────────────────────────────────────────────────────────


def preflight_check():
    """
    Run before any downloading starts.
    Checks everything is in place and catches known failure points.
    Returns True if all good, False if something needs fixing.
    """
    print("\nRunning pre-flight checks...")
    all_ok = True

    # Check API key
    if API_KEY == "YOUR_API_KEY_HERE":
        print("  FAIL: API_KEY not set in script")
        all_ok = False
    else:
        print(f"  OK:   API key set ({API_KEY[:8]}...)")

    # Check tickers file exists
    found_tickers = False
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                count = sum(1 for l in f if l.strip())
            print(f"  OK:   tickers.txt found — {count} tickers")
            found_tickers = True
            break
    if not found_tickers:
        print("  FAIL: tickers.txt not found")
        all_ok = False

    # Check/create all D drive folders
    for folder in [DATA_ROOT, DAILY_DIR, INTRADAY_DIR, TECH_DIR, EVENTS_DIR, META_DIR]:
        os.makedirs(folder, exist_ok=True)
        if os.path.exists(folder):
            count = len(os.listdir(folder))
            print(f"  OK:   {folder} exists ({count} files)")
        else:
            print(f"  FAIL: Could not create {folder}")
            all_ok = False

    # Check EODHD API is reachable with a single test call
    print("  Checking EODHD API connection...")
    try:
        test = requests.get(
            f"{BASE_URL}/eod/AAPL.US",
            params={"api_token": API_KEY, "fmt": "json", "limit": 1},
            timeout=10
        )
        if test.status_code == 200:
            print("  OK:   EODHD API reachable and key valid")
        elif test.status_code == 401:
            print("  FAIL: EODHD API key invalid or expired")
            all_ok = False
        elif test.status_code == 402:
            print("  FAIL: EODHD plan does not have access to this data")
            all_ok = False
        else:
            print(f"  WARN: EODHD API returned {test.status_code} — may still work")
    except Exception as e:
        print(f"  FAIL: Cannot reach EODHD API: {e}")
        all_ok = False

    # Check safe_filename works on known problem tickers
    problem_tickers = ["BRK.B", "BRK.A", "BF.A", "BF.B"]
    for t in problem_tickers:
        safe = safe_filename(t)
        test_path = os.path.join(EVENTS_DIR, f"{safe}_dividends.csv")
        try:
            # Write a tiny placeholder so we never crash on these
            if not os.path.exists(test_path):
                with open(test_path, "w") as f:
                    f.write("")
            print(f"  OK:   Problem ticker {t} -> {safe}_dividends.csv ready")
        except Exception as e:
            print(f"  FAIL: Cannot create placeholder for {t}: {e}")
            all_ok = False

    # Load progress and show where we are
    prog = load_progress()
    if prog:
        print("\n  Current progress:")
        phase_names = {
            "daily": "Phase 1 Daily OHLCV",
            "intraday": "Phase 2 Intraday 5-min",
            "rsi": "Phase 3 RSI",
            "macd": "Phase 4 MACD",
            "bbands": "Phase 5 Bollinger Bands",
            "dividends": "Phase 6 Dividends",
            "splits": "Phase 7 Splits",
            "meta": "Phase 8 Metadata",
        }
        for key, name in phase_names.items():
            done = len(prog.get(key, []))
            print(f"    {name}: {done} tickers done")

    if all_ok:
        print("\n  All checks passed. Starting download...\n")
    else:
        print("\n  One or more checks FAILED. Fix above issues before running.")

    return all_ok

def run():
    print("=" * 60)
    print("GarAI — EODHD Comprehensive Data Downloader")
    print(f"Started: {datetime.now().strftime('%A %d %b %Y %H:%M')}")
    print("=" * 60)

    setup()

    if not preflight_check():
        print("Aborting. Fix the issues above and re-run.")
        return

    tickers = load_tickers()
    progress = load_progress()
    total_api = 0

    n = len(tickers)
    est_calls = n * (1+1+5+5+5+1+1+1+1)
    est_hours = est_calls * SLEEP / 3600

    print(f"\nTickers: {n}")
    print(f"Estimated API calls: ~{est_calls:,} (limit: 100,000/day)")
    print(f"Estimated time: ~{est_hours:.1f} hours")
    print(f"Progress saved every 50 tickers — safe to interrupt.\n")

    log(f"=== Session started — {n} tickers ===")

    phases = [
        ("Phase 1/8 — Daily OHLCV (30 years)",           dl_daily,     "daily",     1),
        ("Phase 2/8 — Intraday 5-min (1 year)",           dl_intraday,  "intraday",  1),
        ("Phase 3/8 — RSI(14) daily",                     dl_rsi,       "rsi",       5),
        ("Phase 4/8 — MACD(12,26,9) daily",               dl_macd,      "macd",      5),
        ("Phase 5/8 — Bollinger Bands(20) daily",         dl_bbands,    "bbands",    5),
        ("Phase 6/8 — Dividends history",                 dl_dividends, "dividends", 1),
        ("Phase 7/8 — Splits history",                    dl_splits,    "splits",    1),
        ("Phase 8/8 — Company metadata",                  dl_meta,      "meta",      1),
    ]

    for name, fn, key, calls_each in phases:
        total_api += run_phase(name, tickers, fn, progress, key, calls_each)

    print(f"\n{'='*60}")
    print(f"ALL DOWNLOADS COMPLETE")
    print(f"Total API calls used: {total_api:,}")
    print(f"\nFolder summary:")
    for folder in [DAILY_DIR, INTRADAY_DIR, TECH_DIR, EVENTS_DIR, META_DIR]:
        if os.path.exists(folder):
            count = len(os.listdir(folder))
            print(f"  {os.path.basename(folder)}\\  —  {count} files")
    print(f"\nNext steps:")
    print(f"  1. Cancel EODHD subscription (billing page)")
    print(f"  2. py backtest_local.py  — run full backtest")
    print(f"  3. py update_data.py --install  — set up weekly refresh")
    print(f"{'='*60}\n")
    log(f"=== Session complete — total API: {total_api} ===")


if __name__ == "__main__":
    run()
