"""
GarAI — Weekly Data Updater
=============================
Downloads only NEW candles since the last update.
Run manually or let Windows Task Scheduler run it automatically
every Sunday morning.

First time: run this script and it will install itself into
Windows Task Scheduler for you. After that, forget about it.

Usage:
  py update_data.py           — run update now
  py update_data.py --install — also schedule weekly auto-run
  py update_data.py --remove  — remove from Task Scheduler

Runtime: 15-25 minutes per weekly update
"""

import yfinance as yf
import pandas as pd
import os
import sys
import time
import random
import subprocess
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

DATA_ROOT     = r"D:\GarAI\data"
DAILY_DIR     = os.path.join(DATA_ROOT, "daily")
INTRADAY_DIR  = os.path.join(DATA_ROOT, "intraday")
PREMARKET_DIR = os.path.join(DATA_ROOT, "premarket")
TICKERS_FILE  = "tickers.txt"
LOG_FILE      = os.path.join(DATA_ROOT, "update_log.txt")

BATCH_SIZE    = 20
SLEEP_MIN     = 3
SLEEP_MAX     = 6

TASK_NAME     = "GarAI_Weekly_Update"

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{timestamp}] {msg}"
    print(line)
    os.makedirs(DATA_ROOT, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Tickers ───────────────────────────────────────────────────────────────────

def load_tickers():
    for path in [TICKERS_FILE, os.path.join("..", TICKERS_FILE)]:
        if os.path.exists(path):
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]
    raise FileNotFoundError(f"Cannot find {TICKERS_FILE}.")


# ── Update helpers ────────────────────────────────────────────────────────────

def get_last_date(filepath):
    """Read the last date in an existing CSV file."""
    try:
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        if df.empty:
            return None
        return df.index[-1].date()
    except Exception:
        return None


def update_daily(tickers):
    """Append new daily candles to existing files."""
    print("\nUpdating daily data...")
    updated = 0
    batches = [tickers[i:i+BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            data = yf.download(
                batch, period="10d", interval="1d",
                auto_adjust=True, progress=False, threads=False
            )
            if data.empty:
                continue

            close = data["Close"] if "Close" in data.columns else pd.DataFrame()

            for t in batch:
                fpath = os.path.join(DAILY_DIR, f"{t}.csv")
                if not os.path.exists(fpath):
                    continue  # only update existing — download_data.py handles new

                last_date = get_last_date(fpath)

                if len(batch) == 1:
                    new_df = data.copy()
                else:
                    if hasattr(close, 'columns') and t not in close.columns:
                        continue
                    new_df = pd.DataFrame({
                        "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                        "High":   data["High"][t]   if "High"   in data.columns else None,
                        "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                        "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                        "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                    })

                new_df = new_df.dropna(how="all")
                if new_df.empty:
                    continue

                # Filter to only truly new rows
                new_df.index = pd.to_datetime(new_df.index)
                if last_date:
                    new_rows = new_df[new_df.index.date > last_date]
                else:
                    new_rows = new_df

                if new_rows.empty:
                    continue

                # Append to existing file
                existing = pd.read_csv(fpath, index_col=0, parse_dates=True)
                combined = pd.concat([existing, new_rows])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined.sort_index(inplace=True)
                combined.to_csv(fpath)
                updated += 1

        except Exception as e:
            log(f"  Daily update batch error: {str(e)[:60]}")

        if (i + 1) % 10 == 0:
            print(f"  Daily: batch {i+1}/{len(batches)}, {updated} files updated")

        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    print(f"  Daily update complete: {updated} files updated")
    return updated


def update_intraday(tickers):
    """Replace intraday files — always re-download 60 days."""
    print("\nUpdating intraday data (re-downloading 60 days)...")
    updated = 0
    batches = [tickers[i:i+BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        try:
            data = yf.download(
                batch, period="60d", interval="5m",
                auto_adjust=True, progress=False, threads=False
            )
            if data.empty:
                continue

            close = data["Close"] if "Close" in data.columns else pd.DataFrame()

            for t in batch:
                fpath = os.path.join(INTRADAY_DIR, f"{t}_5m.csv")
                if not os.path.exists(fpath):
                    continue

                if len(batch) == 1:
                    new_df = data.copy()
                else:
                    if hasattr(close, 'columns') and t not in close.columns:
                        continue
                    new_df = pd.DataFrame({
                        "Open":   data["Open"][t]   if "Open"   in data.columns else None,
                        "High":   data["High"][t]   if "High"   in data.columns else None,
                        "Low":    data["Low"][t]    if "Low"    in data.columns else None,
                        "Close":  data["Close"][t]  if "Close"  in data.columns else None,
                        "Volume": data["Volume"][t] if "Volume" in data.columns else None,
                    })

                new_df = new_df.dropna(how="all")
                if new_df.empty:
                    continue

                new_df.to_csv(fpath)
                updated += 1

        except Exception as e:
            log(f"  Intraday update batch error: {str(e)[:60]}")

        if (i + 1) % 10 == 0:
            print(f"  Intraday: batch {i+1}/{len(batches)}, {updated} files updated")

        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    print(f"  Intraday update complete: {updated} files updated")
    return updated


# ── Windows Task Scheduler ────────────────────────────────────────────────────

def get_script_path():
    """Get the full path to this script."""
    return os.path.abspath(__file__)


def get_python_path():
    """Get the full path to Python executable."""
    return sys.executable


def install_task():
    """Install this script as a weekly Windows Task Scheduler job."""
    script  = get_script_path()
    python  = get_python_path()
    trigger = "WEEKLY"
    day     = "SUN"
    time_s  = "08:00"

    # Build the schtasks command
    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python}" "{script}"',
        "/sc", trigger,
        "/d",  day,
        "/st", time_s,
        "/ru", "SYSTEM",
        "/f"   # overwrite if exists
    ]

    print(f"\nInstalling Windows Task Scheduler job...")
    print(f"  Script:  {script}")
    print(f"  Python:  {python}")
    print(f"  Schedule: Every Sunday at {time_s}")
    print(f"  Task name: {TASK_NAME}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"\nSUCCESS — Task installed.")
            print(f"  The updater will now run automatically every Sunday at {time_s}.")
            print(f"  You can view/edit it in Windows Task Scheduler (search in Start menu).")
            log(f"Task Scheduler job installed: {TASK_NAME}")
        else:
            print(f"\nTask install failed: {result.stderr}")
            print("\nManual alternative — open Task Scheduler and create a task with:")
            print(f"  Program: {python}")
            print(f"  Arguments: {script}")
            print(f"  Trigger: Weekly, Sunday, 08:00")
    except Exception as e:
        print(f"\nCould not install task: {e}")
        print("\nRun Command Prompt as Administrator and try again,")
        print("or set up the task manually in Windows Task Scheduler.")


def remove_task():
    """Remove the scheduled task."""
    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"Task '{TASK_NAME}' removed from Task Scheduler.")
        else:
            print(f"Could not remove task: {result.stderr}")
    except Exception as e:
        print(f"Error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_update():
    print("=" * 60)
    print("GarAI — Weekly Data Updater")
    print(f"Run: {datetime.now().strftime('%A %d %b %Y %H:%M')}")
    print("=" * 60)

    if not os.path.exists(DATA_ROOT):
        print(f"\nERROR: {DATA_ROOT} not found.")
        print("Run download_data.py first to build the initial dataset.")
        return

    tickers = load_tickers()
    print(f"\nLoaded {len(tickers)} tickers")
    log(f"=== Weekly update started — {len(tickers)} tickers ===")

    d_count = update_daily(tickers)
    i_count = update_intraday(tickers)

    print(f"\n{'='*60}")
    print(f"Update complete.")
    print(f"  Daily files updated:    {d_count}")
    print(f"  Intraday files updated: {i_count}")
    log(f"=== Weekly update complete — daily: {d_count}, intraday: {i_count} ===")


if __name__ == "__main__":
    if "--install" in sys.argv:
        run_update()
        install_task()
    elif "--remove" in sys.argv:
        remove_task()
    else:
        run_update()
