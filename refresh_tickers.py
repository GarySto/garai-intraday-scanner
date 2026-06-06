"""
GarAI — T212 Ticker Refresh
=============================
Pulls the full tradeable instrument list from Trading 212 API
and writes a clean tickers.txt for both scanner projects.

Covers both ISA and Invest sections of your T212 account.
Runs as part of daily_update.py or standalone.

Usage:
  py refresh_tickers.py              — refresh tickers.txt
  py refresh_tickers.py --stats      — show breakdown by exchange/type

API required: Metadata permission only (read-only, safe)
Rate limit:   1 request per 50 seconds on this endpoint
              (only needs to run once daily so never an issue)

Output:
  tickers.txt         — clean US tickers, one per line
  tickers_full.json   — full instrument data for reference
  tickers_stats.txt   — breakdown by exchange, type, currency
"""

import os
import sys
import json
import time
import requests
import pandas as pd
from datetime import datetime
import pytz

# ── Config ────────────────────────────────────────────────────────────────────

T212_API_KEY  = os.environ.get("T212_API_KEY", "YOUR_T212_KEY_HERE")
T212_BASE     = "https://live.trading212.com/api/v0"

TICKERS_FILE  = "tickers.txt"
FULL_JSON     = "tickers_full.json"
STATS_FILE    = "tickers_stats.txt"

BST = pytz.timezone("Europe/London")


# ── Fetch from T212 ───────────────────────────────────────────────────────────

def fetch_instruments():
    """
    Fetch all instruments from T212 API.
    Returns list of instrument dicts or None on failure.

    Each instrument has:
      ticker        — e.g. "AAPL_US_EQ"
      shortName     — e.g. "AAPL"
      name          — e.g. "Apple"
      type          — "STOCK" or "ETF"
      currencyCode  — "USD", "GBP" etc.
      exchange      — "NASDAQ", "NYSE" etc.
      minTradeQuantity
      maxOpenQuantity
    """
    if T212_API_KEY == "YOUR_T212_KEY_HERE":
        print("ERROR: T212_API_KEY not set.")
        print("Set it as an environment variable or paste into the script.")
        return None

    headers = {"Authorization": T212_API_KEY}
    url     = f"{T212_BASE}/equity/metadata/instruments"

    print(f"Fetching instruments from T212 API...")
    try:
        r = requests.get(url, headers=headers, timeout=30)

        if r.status_code == 401:
            print("ERROR: Invalid API key or key has expired.")
            print("Generate a new key at app.trading212.com → Settings → API.")
            return None

        if r.status_code == 403:
            print("ERROR: API key missing Metadata permission.")
            print("Regenerate key with Metadata permission enabled.")
            return None

        if r.status_code == 429:
            print("Rate limited. This endpoint allows 1 request per 50 seconds.")
            print("Wait 60 seconds and try again.")
            return None

        if r.status_code != 200:
            print(f"ERROR: T212 API returned {r.status_code}: {r.text[:200]}")
            return None

        instruments = r.json()
        print(f"  Received {len(instruments)} instruments from T212")
        return instruments

    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to T212 API. Check internet connection.")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None


# ── Filter and clean ──────────────────────────────────────────────────────────

def extract_us_tickers(instruments):
    """
    Extract clean US stock tickers from the instrument list.

    T212 ticker format: AAPL_US_EQ, MSFT_US_EQ etc.
    Some instruments use shortName directly.

    Filters:
    - US equities only (_US_EQ suffix or USD currency on US exchange)
    - Clean uppercase ticker symbol
    - No slash characters (yfinance can't handle BRK/B format)
    - Length 1-6 characters (standard US ticker range)
    """
    us_tickers  = []
    etf_tickers = []
    other       = []

    for inst in instruments:
        raw_ticker = inst.get("ticker", "")
        short_name = inst.get("shortName", "")
        inst_type  = inst.get("type", "")
        currency   = inst.get("currencyCode", "")
        exchange   = inst.get("exchange", "")

        # Determine clean ticker
        if "_US_EQ" in raw_ticker:
            clean = raw_ticker.replace("_US_EQ", "")
        elif raw_ticker.endswith("_EQ") and currency == "USD":
            clean = raw_ticker.replace("_EQ", "")
        elif short_name and currency == "USD" and exchange in [
            "NASDAQ", "NYSE", "NYSE ARCA", "NYSE AMERICAN",
            "BATS", "OTC MARKETS"
        ]:
            clean = short_name
        else:
            other.append(inst)
            continue

        # Validate ticker format
        if not clean:
            continue
        if "/" in clean or "\\" in clean:
            continue
        if not clean.replace(".", "").isupper():
            continue
        if len(clean) > 6:
            continue

        inst_copy = dict(inst)
        inst_copy["clean_ticker"] = clean

        if inst_type == "ETF":
            etf_tickers.append(inst_copy)
        else:
            us_tickers.append(inst_copy)

    return us_tickers, etf_tickers, other


# ── Stats ─────────────────────────────────────────────────────────────────────

def build_stats(us_stocks, etfs, other, all_instruments):
    lines = []
    lines.append("=" * 50)
    lines.append("T212 Instrument List — Statistics")
    lines.append(f"Updated: {datetime.now(BST).strftime('%d %b %Y %H:%M BST')}")
    lines.append("=" * 50)
    lines.append(f"\nTotal instruments: {len(all_instruments)}")
    lines.append(f"US stocks:         {len(us_stocks)}")
    lines.append(f"US ETFs:           {len(etfs)}")
    lines.append(f"Other/excluded:    {len(other)}")

    # Exchange breakdown for US stocks
    lines.append(f"\nUS stocks by exchange:")
    exchanges = {}
    for inst in us_stocks:
        ex = inst.get("exchange", "Unknown")
        exchanges[ex] = exchanges.get(ex, 0) + 1
    for ex, count in sorted(exchanges.items(), key=lambda x: -x[1]):
        lines.append(f"  {ex}: {count}")

    # ETF exchanges
    if etfs:
        lines.append(f"\nETFs by exchange:")
        etf_exchanges = {}
        for inst in etfs:
            ex = inst.get("exchange", "Unknown")
            etf_exchanges[ex] = etf_exchanges.get(ex, 0) + 1
        for ex, count in sorted(etf_exchanges.items(), key=lambda x: -x[1]):
            lines.append(f"  {ex}: {count}")

    lines.append(f"\n{'='*50}\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print("=" * 50)
    print("GarAI — T212 Ticker Refresh")
    print(f"Run: {datetime.now(BST).strftime('%d %b %Y %H:%M BST')}")
    print("=" * 50)

    instruments = fetch_instruments()
    if not instruments:
        return False

    # Extract US tickers
    us_stocks, etfs, other = extract_us_tickers(instruments)
    all_us = us_stocks + etfs  # include ETFs — tradeable and useful

    print(f"\nBreakdown:")
    print(f"  US stocks: {len(us_stocks)}")
    print(f"  US ETFs:   {len(etfs)}")
    print(f"  Other:     {len(other)}")
    print(f"  Total for tickers.txt: {len(all_us)}")

    # Sort alphabetically
    all_us.sort(key=lambda x: x["clean_ticker"])
    ticker_list = [inst["clean_ticker"] for inst in all_us]

    # Save tickers.txt
    with open(TICKERS_FILE, "w") as f:
        f.write("\n".join(ticker_list))
    print(f"\nSaved {len(ticker_list)} tickers to {TICKERS_FILE}")

    # Save full JSON for reference
    with open(FULL_JSON, "w", encoding="utf-8") as f:
        json.dump(all_us, f, indent=2)
    print(f"Saved full instrument data to {FULL_JSON}")

    # Build and save stats
    stats = build_stats(us_stocks, etfs, other, instruments)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        f.write(stats)

    if "--stats" in sys.argv:
        print("\n" + stats)

    print(f"\nDone. {len(ticker_list)} tickers ready for both scanners.")
    print(f"Copy tickers.txt to market-universe-generator repo too:")
    print(f"  copy tickers.txt ..\\market-universe-generator\\tickers.txt")
    return True


if __name__ == "__main__":
    run()
