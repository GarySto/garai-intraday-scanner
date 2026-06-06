"""
GarAI — T212 Ticker Refresh
=============================
Pulls the full tradeable instrument list from Trading 212 API
and writes a clean tickers.txt for both scanner projects.

IMPORTANT: T212 API uses HTTP Basic Authentication.
You need BOTH an API Key AND an API Secret.
Generate both at: app.trading212.com -> Settings -> API

Rate limit: 1 request per 50 seconds on the instruments endpoint.

Usage:
  py refresh_tickers.py              — refresh tickers.txt
  py refresh_tickers.py --stats      — show breakdown by exchange/type
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
# T212 uses HTTP Basic Auth: Key = username, Secret = password
# Generate BOTH at app.trading212.com -> Settings -> API
# Paste them below for local use, or set as environment variables

T212_API_KEY    = os.environ.get("T212_API_KEY",    "4538584ZnuslpjyVkEkklOdihENyLBCUnFmx")
T212_API_SECRET = os.environ.get("T212_API_SECRET", "vILqsom6mLPxd6UupISh-5Rng1v2dLnAm0qaYGdagqY")
T212_BASE       = "https://live.trading212.com/api/v0"

TICKERS_FILE = "tickers.txt"
FULL_JSON    = "tickers_full.json"
STATS_FILE   = "tickers_stats.txt"

BST = pytz.timezone("Europe/London")


def fetch_instruments():
    """Fetch all instruments using Basic Auth (Key + Secret)."""
    if T212_API_KEY == "YOUR_T212_KEY_HERE":
        print("ERROR: Paste your T212 API Key into the script on line 26")
        return None
    if T212_API_SECRET == "YOUR_T212_SECRET_HERE":
        print("ERROR: Paste your T212 API Secret into the script on line 27")
        print("T212 requires BOTH a Key AND Secret — generate both in the T212 app")
        return None

    url = f"{T212_BASE}/equity/metadata/instruments"
    print("Fetching instruments from T212 API...")
    print("(Note: this endpoint has a 50-second rate limit)")

    try:
        r = requests.get(url, auth=(T212_API_KEY, T212_API_SECRET), timeout=30)

        if r.status_code == 401:
            print("ERROR: Invalid credentials.")
            print("Make sure you have the correct Key AND Secret from T212.")
            return None
        if r.status_code == 403:
            print("ERROR: Missing Metadata permission on your API key.")
            return None
        if r.status_code == 429:
            print("Rate limited — wait 60 seconds and try again.")
            return None
        if r.status_code != 200:
            print(f"ERROR: T212 returned {r.status_code}: {r.text[:200]}")
            return None

        instruments = r.json()
        print(f"  Received {len(instruments)} instruments")
        return instruments

    except Exception as e:
        print(f"ERROR: {e}")
        return None


def extract_us_tickers(instruments):
    us_stocks  = []
    etf_tickers = []
    other      = []

    for inst in instruments:
        raw_ticker = inst.get("ticker", "")
        short_name = inst.get("shortName", "")
        inst_type  = inst.get("type", "")
        currency   = inst.get("currencyCode", "")
        exchange   = inst.get("exchange", "")

        if "_US_EQ" in raw_ticker:
            clean = raw_ticker.replace("_US_EQ", "")
        elif raw_ticker.endswith("_EQ") and currency == "USD":
            clean = raw_ticker.replace("_EQ", "")
        elif short_name and currency == "USD" and exchange in [
            "NASDAQ", "NYSE", "NYSE ARCA", "NYSE AMERICAN", "BATS", "OTC MARKETS"
        ]:
            clean = short_name
        else:
            other.append(inst)
            continue

        if not clean or "/" in clean or len(clean) > 6:
            continue
        if not clean.replace(".", "").isupper():
            continue

        inst_copy = dict(inst)
        inst_copy["clean_ticker"] = clean

        if inst_type == "ETF":
            etf_tickers.append(inst_copy)
        else:
            us_stocks.append(inst_copy)

    return us_stocks, etf_tickers, other


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

    lines.append(f"\nUS stocks by exchange:")
    exchanges = {}
    for inst in us_stocks:
        ex = inst.get("exchange", "Unknown")
        exchanges[ex] = exchanges.get(ex, 0) + 1
    for ex, count in sorted(exchanges.items(), key=lambda x: -x[1]):
        lines.append(f"  {ex}: {count}")

    lines.append(f"\n{'='*50}\n")
    return "\n".join(lines)


def run():
    print("=" * 50)
    print("GarAI — T212 Ticker Refresh")
    print(f"Run: {datetime.now(BST).strftime('%d %b %Y %H:%M BST')}")
    print("=" * 50)

    instruments = fetch_instruments()
    if not instruments:
        return False

    us_stocks, etfs, other = extract_us_tickers(instruments)
    all_us = us_stocks + etfs
    all_us.sort(key=lambda x: x["clean_ticker"])
    ticker_list = [inst["clean_ticker"] for inst in all_us]

    print(f"\nUS stocks: {len(us_stocks)}  |  ETFs: {len(etfs)}  |  Other: {len(other)}")
    print(f"Total for tickers.txt: {len(ticker_list)}")

    with open(TICKERS_FILE, "w") as f:
        f.write("\n".join(ticker_list))
    print(f"Saved {len(ticker_list)} tickers to {TICKERS_FILE}")

    with open(FULL_JSON, "w", encoding="utf-8") as f:
        json.dump(all_us, f, indent=2)

    stats = build_stats(us_stocks, etfs, other, instruments)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        f.write(stats)

    if "--stats" in sys.argv:
        print("\n" + stats)

    print(f"\nDone. Copy tickers to premarket scanner:")
    print(f"  copy tickers.txt ..\\market-universe-generator\\tickers.txt")
    return True


if __name__ == "__main__":
    run()
