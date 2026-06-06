"""
GarAI — Market Events & Regime Context
========================================
Adds market regime and event context to backtest results.

This module is imported by backtest_local.py and adds three
columns to every signal in the backtest results:

  market_regime   — Bull / Bear / Volatile / Crisis / Recovery
  event_name      — Name of any concurrent market event (or "None")
  sectors_context — Whether signal sector was helped/hurt/neutral

Why this matters:
  A 4-touch support bounce in a bull market may have a 54% win rate.
  The same signal in a bear market or crisis may perform very differently.
  Without regime context, your backtest findings may only be valid for
  the specific market conditions in your data window.

Usage:
  from market_context import add_market_context
  df = add_market_context(df)  # adds columns to your backtest DataFrame

Also provides:
  print_regime_summary(df)  — shows win rates split by market regime
"""

import pandas as pd
import os
from datetime import datetime

EVENTS_FILE = "market_events.csv"

# Sector mapping — maps EODHD sector names to simplified categories
# Used to determine if a stock's sector was impacted by an event
SECTOR_MAP = {
    "Technology":             "Technology",
    "Communication Services": "Telecom",
    "Consumer Discretionary": "Consumer",
    "Consumer Staples":       "Consumer Staples",
    "Energy":                 "Oil",
    "Financials":             "Financials",
    "Health Care":            "Healthcare",
    "Industrials":            "Industrials",
    "Materials":              "Materials",
    "Real Estate":            "REITs",
    "Utilities":              "Utilities",
    "Defence":                "Defence",
    "Airlines":               "Airlines",
    "Travel":                 "Travel",
}


def load_events():
    """Load the market events CSV."""
    for path in [EVENTS_FILE, os.path.join("..", EVENTS_FILE)]:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=["date_start", "date_end"])
            return df
    print(f"Warning: {EVENTS_FILE} not found. Run from garai-intraday-scanner folder.")
    return pd.DataFrame()


def load_ticker_sectors():
    """
    Load sector data from D:\\GarAI\\data\\meta\\ if available.
    Returns dict: {ticker: sector}
    """
    meta_dir = r"D:\GarAI\data\meta"
    sectors = {}
    if not os.path.exists(meta_dir):
        return sectors

    import json
    for fname in os.listdir(meta_dir):
        if not fname.endswith("_meta.json"):
            continue
        try:
            with open(os.path.join(meta_dir, fname), encoding="utf-8") as f:
                meta = json.load(f)
            ticker = meta.get("ticker", "")
            sector = meta.get("sector", "")
            if ticker and sector:
                sectors[ticker] = sector
        except Exception:
            pass

    print(f"Loaded sector data for {len(sectors)} tickers from meta folder")
    return sectors


def get_regime_for_date(signal_date, events_df):
    """
    Find the market regime and any concurrent events for a given date.
    Returns (regime, event_name, severity)
    """
    if events_df.empty:
        return "Unknown", "None", "Unknown"

    if isinstance(signal_date, str):
        signal_date = pd.to_datetime(signal_date)

    # Find events that were active on this date
    active = events_df[
        (events_df["date_start"] <= signal_date) &
        (events_df["date_end"] >= signal_date)
    ]

    if active.empty:
        # No specific event — determine general regime from nearest event
        past = events_df[events_df["date_end"] < signal_date]
        if not past.empty:
            last = past.iloc[-1]
            regime = last["regime"]
        else:
            regime = "Pre-data"
        return regime, "None", "Normal"

    # If multiple events overlap, take the most severe
    severity_order = {"Extreme": 5, "Severe": 4, "Moderate": 3, "Low": 2, "Normal": 1}
    active = active.copy()
    active["sev_score"] = active["severity"].map(severity_order).fillna(1)
    primary = active.sort_values("sev_score", ascending=False).iloc[0]

    return (
        str(primary["regime"]),
        str(primary["event_name"]),
        str(primary["severity"])
    )


def get_sector_context(ticker, signal_date, events_df, ticker_sectors):
    """
    Determine if the ticker's sector was helped or hurt by concurrent events.
    Returns: "Hurt" / "Helped" / "Neutral" / "Unknown"
    """
    sector = ticker_sectors.get(ticker, "")
    if not sector or events_df.empty:
        return "Unknown"

    if isinstance(signal_date, str):
        signal_date = pd.to_datetime(signal_date)

    active = events_df[
        (events_df["date_start"] <= signal_date) &
        (events_df["date_end"] >= signal_date)
    ]

    if active.empty:
        return "Neutral"

    for _, event in active.iterrows():
        hurt    = str(event.get("sectors_impacted", ""))
        helped  = str(event.get("sectors_helped", ""))

        # Check if this sector appears in the hurt or helped lists
        for s in hurt.split(","):
            if sector.lower() in s.lower() or s.lower() in sector.lower():
                return "Hurt"
        for s in helped.split(","):
            if sector.lower() in s.lower() or s.lower() in sector.lower():
                return "Helped"

    return "Neutral"


def add_market_context(df, verbose=True):
    """
    Main function — adds market regime context columns to a backtest DataFrame.

    Input:  DataFrame with at least a 'date' column and 'ticker' column
    Output: Same DataFrame with added columns:
              market_regime, event_name, event_severity, sector_context
    """
    if df.empty:
        return df

    events_df     = load_events()
    ticker_sectors = load_ticker_sectors()

    if events_df.empty:
        if verbose:
            print("No events data — add market_events.csv to enable regime analysis")
        df["market_regime"]   = "Unknown"
        df["event_name"]      = "None"
        df["event_severity"]  = "Unknown"
        df["sector_context"]  = "Unknown"
        return df

    if verbose:
        print(f"Adding market context to {len(df)} signals...")

    regimes        = []
    event_names    = []
    severities     = []
    sector_contexts = []

    for _, row in df.iterrows():
        signal_date = row.get("date", "")
        ticker      = row.get("ticker", "")

        regime, event, severity = get_regime_for_date(signal_date, events_df)
        sector_ctx = get_sector_context(ticker, signal_date, events_df, ticker_sectors)

        regimes.append(regime)
        event_names.append(event)
        severities.append(severity)
        sector_contexts.append(sector_ctx)

    df = df.copy()
    df["market_regime"]  = regimes
    df["event_name"]     = event_names
    df["event_severity"] = severities
    df["sector_context"] = sector_contexts

    if verbose:
        print(f"Done. Regime breakdown:")
        for regime, count in df["market_regime"].value_counts().items():
            print(f"  {regime}: {count} signals")

    return df


def print_regime_summary(df, outcome_col="return_3d_pct", mode_filter=None):
    """
    Print win rates and average returns split by market regime.
    Helps answer: 'does this strategy work across all market conditions?'

    outcome_col:  column to measure (return_1h_pct, return_3d_pct etc.)
    mode_filter:  optional — filter to one mode e.g. "SUPPORT_BOUNCE"
    """
    if "market_regime" not in df.columns:
        print("No market_regime column — run add_market_context() first")
        return

    sub = df.copy()
    if mode_filter:
        sub = sub[sub["mode"] == mode_filter]
    if outcome_col not in sub.columns:
        print(f"Column {outcome_col} not found")
        return

    print(f"\n{'='*60}")
    print(f"Win rates by market regime")
    if mode_filter:
        print(f"Mode: {mode_filter}  |  Outcome: {outcome_col}")
    print(f"{'='*60}")

    for regime in sorted(sub["market_regime"].unique()):
        band  = sub[sub["market_regime"] == regime]
        valid = band[outcome_col].dropna()
        if valid.empty:
            continue
        win_rate = (valid > 0).sum() / len(valid) * 100
        avg_ret  = valid.mean()
        print(f"  {regime:12s}: {len(band):5d} signals  |  "
              f"win {win_rate:4.0f}%  |  avg {avg_ret:+.2f}%")

    print(f"\nEvent context breakdown:")
    for event in sub["event_name"].value_counts().head(10).index:
        band  = sub[sub["event_name"] == event]
        valid = band[outcome_col].dropna()
        if valid.empty:
            continue
        win_rate = (valid > 0).sum() / len(valid) * 100
        avg_ret  = valid.mean()
        print(f"  {event[:30]:30s}: {len(band):4d} signals  |  "
              f"win {win_rate:4.0f}%  |  avg {avg_ret:+.2f}%")

    print(f"\nSector context breakdown:")
    for ctx in ["Hurt", "Helped", "Neutral", "Unknown"]:
        band  = sub[sub["sector_context"] == ctx]
        valid = band[outcome_col].dropna()
        if valid.empty:
            continue
        win_rate = (valid > 0).sum() / len(valid) * 100
        avg_ret  = valid.mean()
        print(f"  Sector {ctx:7s}: {len(band):5d} signals  |  "
              f"win {win_rate:4.0f}%  |  avg {avg_ret:+.2f}%")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    # Quick test
    events = load_events()
    print(f"Loaded {len(events)} market events")
    print("\nSample regime lookups:")
    test_dates = [
        "2001-09-12",  # 9/11
        "2008-10-01",  # Financial crisis
        "2020-03-15",  # COVID crash
        "2022-06-01",  # Rate hike bear market
        "2023-06-01",  # AI bull market
        "2025-04-05",  # Trump tariff crash
    ]
    for d in test_dates:
        regime, event, sev = get_regime_for_date(d, events)
        print(f"  {d}: {regime} — {event} ({sev})")
