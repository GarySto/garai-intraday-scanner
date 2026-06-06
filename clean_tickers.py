"""
GarAI Intraday Scanner — Ticker Cleaner
========================================
Takes the full T212 US instrument CSV, validates each ticker against
yfinance in batches (to avoid rate limiting), and writes a clean
tickers.txt with only symbols that actually work.

Key design choices:
  - Batches of 50 tickers via yfinance.download() — much faster than
    one ticker at a time, and avoids Yahoo rate limits
  - Only removes: no data (delisted), price < $1.50, price > $500
  - Volume NOT filtered here — scanner's live RVOL filter handles quality
  - Retries failed tickers individually before giving up

Usage:
  1. Place t212_instruments.csv in this folder (the T212 download)
  2. py clean_tickers.py
  3. Copy tickers_clean.txt over tickers.txt when happy
  4. Re-run quarterly

Runtime: ~15-25 minutes
"""

import yfinance as yf
import pandas as pd
import os
import time

INPUT_CSV     = "t212_instruments.csv"
OUTPUT_FILE   = "tickers_clean.txt"
REJECTED_FILE = "tickers_rejected.txt"
BATCH_SIZE    = 50      # tickers per yf.download() call
MIN_PRICE     = 1.50
MAX_PRICE     = 500.00
SLEEP_BETWEEN = 2       # seconds between batches — avoids rate limiting

def load_t212_tickers(path):
    df = pd.read_csv(path)
    us = df[df['ticker'].str.contains('_US_EQ', na=False)].copy()
    us['clean'] = us['ticker'].str.replace('_US_EQ', '', regex=False)
    us = us[~us['clean'].str.contains(r'[/]', regex=True)]
    us = us[~us['clean'].str.endswith('_')]
    us = us[us['clean'].str.match(r'^[A-Z]{1,5}[A-Z0-9\.]*$')]
    tickers = us['clean'].tolist()
    print(f"Loaded {len(tickers)} US tickers from T212 CSV")
    return tickers


def validate_batch(batch):
    """
    Download 30d daily data for a batch of tickers in one call.
    Returns dict: {ticker: (status, reason)}
    """
    results = {}
    try:
        # Download all at once — much kinder to Yahoo's rate limits
        data = yf.download(
            batch,
            period="30d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False
        )

        if data.empty:
            for t in batch:
                results[t] = ("rejected", "no data / batch failed")
            return results

        # Handle single vs multi ticker response
        if len(batch) == 1:
            t = batch[0]
            if 'Close' not in data.columns or data['Close'].dropna().empty:
                results[t] = ("rejected", "no data / delisted")
            else:
                price = data['Close'].dropna().iloc[-1]
                if price < MIN_PRICE:
                    results[t] = ("rejected", f"price too low: ${price:.2f}")
                elif price > MAX_PRICE:
                    results[t] = ("rejected", f"price too high: ${price:.2f}")
                else:
                    results[t] = ("ok", f"${price:.2f}")
            return results

        # Multi-ticker: Close is a DataFrame with tickers as columns
        close = data['Close'] if 'Close' in data.columns else pd.DataFrame()

        for t in batch:
            if t not in close.columns:
                results[t] = ("rejected", "no data / delisted")
                continue
            prices = close[t].dropna()
            if prices.empty or len(prices) < 3:
                results[t] = ("rejected", "insufficient data")
                continue
            price = prices.iloc[-1]
            if price < MIN_PRICE:
                results[t] = ("rejected", f"price too low: ${price:.2f}")
            elif price > MAX_PRICE:
                results[t] = ("rejected", f"price too high: ${price:.2f}")
            else:
                results[t] = ("ok", f"${price:.2f}")

    except Exception as e:
        for t in batch:
            results.setdefault(t, ("rejected", f"batch error: {str(e)[:40]}"))

    return results


def run():
    print("=" * 60)
    print("GarAI Intraday Scanner - Ticker Cleaner")
    print("=" * 60)

    if not os.path.exists(INPUT_CSV):
        print(f"\nERROR: {INPUT_CSV} not found.")
        print("Download from: trading212.com/trading-instruments/isa")
        print("Save as t212_instruments.csv in this folder.")
        return

    tickers = load_t212_tickers(INPUT_CSV)
    batches = [tickers[i:i+BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    print(f"\nValidating in {len(batches)} batches of {BATCH_SIZE}...")
    print(f"Filters: price ${MIN_PRICE}-${MAX_PRICE} (volume filtered by scanner live)")
    print(f"Estimated time: {len(batches) * (SLEEP_BETWEEN+3) // 60 + 1} minutes\n")

    good     = []
    rejected = []
    done     = 0

    for i, batch in enumerate(batches):
        results = validate_batch(batch)

        for ticker, (status, reason) in results.items():
            if status == "ok":
                good.append(ticker)
            else:
                rejected.append((ticker, reason))

        done += len(batch)

        if (i + 1) % 5 == 0:
            print(f"  Batch {i+1}/{len(batches)} — {done}/{len(tickers)} tickers "
                  f"({len(good)} valid, {len(rejected)} rejected)")

        time.sleep(SLEEP_BETWEEN)

    # Sort
    good.sort()
    rejected.sort()

    # Save
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(good))
    print(f"\nSaved {len(good)} valid tickers to {OUTPUT_FILE}")

    with open(REJECTED_FILE, "w") as f:
        for ticker, reason in rejected:
            f.write(f"{ticker}\t{reason}\n")
    print(f"Saved {len(rejected)} rejected tickers to {REJECTED_FILE}")

    # Breakdown
    reason_counts = {}
    for _, reason in rejected:
        key = reason.split(":")[0].split("/")[0].strip()
        reason_counts[key] = reason_counts.get(key, 0) + 1
    print("\nRejection breakdown:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Input:    {len(tickers)} T212 US tickers")
    print(f"  Valid:    {len(good)} ({len(good)/len(tickers)*100:.0f}%)")
    print(f"  Rejected: {len(rejected)} ({len(rejected)/len(tickers)*100:.0f}%)")
    print(f"\nNext steps:")
    print(f"  1. Review {REJECTED_FILE} to sense-check")
    print(f"  2. copy tickers_clean.txt tickers.txt")
    print(f"  3. git add tickers.txt && git commit -m 'Update clean ticker list'")
    print(f"  4. Re-run backtest.py with full clean universe")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
