"""
GarAI Intraday Scanner — Winner Analysis
==========================================
Reads backtest_results.csv and finds what separates
Mode 1 signals that hit +10% from the ones that didn't.

Also analyses Mode 2 support bounce winners vs losers.

Run from your garai-intraday-scanner folder:
  py analyse_winners.py

Output:
  winner_analysis.txt  — full findings
"""

import pandas as pd
import numpy as np
import os

INPUT_FILE  = "backtest_results.csv"
OUTPUT_FILE = "winner_analysis.txt"

# What counts as a "winner" for each mode
M1_WIN_THRESHOLD   = 5.0   # % session gain to count as a good Mode 1 trade
M1_LOSS_THRESHOLD  = -2.0  # % 1hr loss to count as a clear loser
M2_WIN_THRESHOLD   = 3.0   # % 3d gain to count as a good Mode 2 trade
M2_LOSS_THRESHOLD  = -2.0  # % 3d loss to count as a clear loser

# ── Load data ─────────────────────────────────────────────────────────────────

def load():
    for p in [INPUT_FILE, os.path.join("..", INPUT_FILE)]:
        if os.path.exists(p):
            return pd.read_csv(p)
    raise FileNotFoundError(f"Cannot find {INPUT_FILE}. Run from garai-intraday-scanner folder.")


def pct_bar(val, total, width=20):
    """Simple ASCII bar for percentages."""
    filled = int(round(val / total * width)) if total > 0 else 0
    return f"[{'#' * filled}{'.' * (width - filled)}] {val} ({val/total*100:.0f}%)"


def compare_groups(winners, losers, col, label, lines, bins=None):
    """Compare a numeric column between winners and losers."""
    w = winners[col].dropna()
    l = losers[col].dropna()
    if w.empty or l.empty:
        return

    lines.append(f"\n  {label}:")
    lines.append(f"    Winners  — avg: {w.mean():+.2f}  median: {w.median():+.2f}  "
                 f"p25: {w.quantile(0.25):+.2f}  p75: {w.quantile(0.75):+.2f}")
    lines.append(f"    Losers   — avg: {l.mean():+.2f}  median: {l.median():+.2f}  "
                 f"p25: {l.quantile(0.25):+.2f}  p75: {l.quantile(0.75):+.2f}")

    # T-test style significance note
    diff = w.mean() - l.mean()
    lines.append(f"    Difference: {diff:+.2f}  {'** Meaningful gap' if abs(diff) > 0.3 else '(small gap)'}")

    # Distribution breakdown if bins provided
    if bins:
        lines.append(f"    Distribution by band:")
        for lo, hi, name in bins:
            w_in = ((w >= lo) & (w < hi)).sum()
            l_in = ((l >= lo) & (l < hi)).sum()
            w_pct = w_in / len(w) * 100 if len(w) > 0 else 0
            l_pct = l_in / len(l) * 100 if len(l) > 0 else 0
            lines.append(f"      {name:15s}  winners: {w_pct:4.0f}%  losers: {l_pct:4.0f}%"
                         + ("  << winners concentrate here" if w_pct > l_pct + 10 else
                            "  << losers concentrate here" if l_pct > w_pct + 10 else ""))


def analyse_time_of_day(winners, losers, lines):
    """Break down win/loss by hour of day."""
    lines.append(f"\n  Time of day (BST hour):")
    all_times = pd.concat([winners, losers])
    if "scan_time" not in all_times.columns:
        return

    def extract_hour(t):
        try:
            return int(str(t).split(":")[0].split()[-1])
        except Exception:
            return None

    all_times = all_times.copy()
    all_times["hour"] = all_times["scan_time"].apply(extract_hour)
    winners_h = winners.copy()
    winners_h["hour"] = winners_h["scan_time"].apply(extract_hour)
    losers_h  = losers.copy()
    losers_h["hour"]  = losers_h["scan_time"].apply(extract_hour)

    for hour in sorted(all_times["hour"].dropna().unique()):
        w_ct = (winners_h["hour"] == hour).sum()
        l_ct = (losers_h["hour"]  == hour).sum()
        tot  = w_ct + l_ct
        if tot == 0:
            continue
        win_rate = w_ct / (w_ct + l_ct) * 100
        lines.append(f"    {int(hour):02d}:xx BST  winners: {w_ct:4d}  losers: {l_ct:4d}  "
                     f"win rate: {win_rate:4.0f}%"
                     + ("  << strong hour" if win_rate > 55 else
                        "  << weak hour"   if win_rate < 40 else ""))


def analyse_m1(df, lines):
    lines.append("\n" + "=" * 60)
    lines.append("MODE 1 — MOMENTUM: WINNER vs LOSER ANALYSIS")
    lines.append("=" * 60)

    m1 = df[df["mode"] == "MODE1_MOMENTUM"].copy()
    if m1.empty:
        lines.append("No Mode 1 signals found.")
        return

    # Define winners and losers
    if "max_gain_session_pct" not in m1.columns:
        lines.append("max_gain_session_pct column not found — re-run backtest.")
        return

    winners = m1[m1["max_gain_session_pct"] >= M1_WIN_THRESHOLD]
    losers  = m1[m1["return_1h_pct"] <= M1_LOSS_THRESHOLD]
    neutral = m1[~m1.index.isin(winners.index) & ~m1.index.isin(losers.index)]

    lines.append(f"\nTotal Mode 1 signals: {len(m1)}")
    lines.append(f"Winners (max session gain >= {M1_WIN_THRESHOLD}%): {len(winners)} "
                 f"({len(winners)/len(m1)*100:.0f}%)")
    lines.append(f"Losers  (1hr return <= {M1_LOSS_THRESHOLD}%):      {len(losers)} "
                 f"({len(losers)/len(m1)*100:.0f}%)")
    lines.append(f"Neutral (between):                      {len(neutral)} "
                 f"({len(neutral)/len(m1)*100:.0f}%)")

    if winners.empty or losers.empty:
        lines.append("\nNot enough winners or losers to compare.")
        return

    lines.append(f"\n{'─'*40}")
    lines.append("SIGNAL CHARACTERISTICS")
    lines.append(f"{'─'*40}")

    # % from open
    compare_groups(winners, losers, "pct_from_open", "% from open at signal time", lines,
                   bins=[(3,5,"3-5%"), (5,8,"5-8%"), (8,15,"8-15%"), (15,100,"15%+")])

    # RVOL
    compare_groups(winners, losers, "rvol", "RVOL at signal time", lines,
                   bins=[(2,3,"2-3x"), (3,5,"3-5x"), (5,10,"5-10x"), (10,100,"10x+")])

    # Score
    compare_groups(winners, losers, "score", "Scanner score", lines,
                   bins=[(0,4,"0-4"), (4,6,"4-6"), (6,8,"6-8"), (8,10,"8-10")])

    # Time of day
    analyse_time_of_day(winners, losers, lines)

    # Entry price (proxy for stock price range)
    compare_groups(winners, losers, "entry_price", "Stock price at entry", lines,
                   bins=[(1.5,5,"$1.50-5"), (5,15,"$5-15"), (15,30,"$15-30"),
                         (30,50,"$30-50"), (50,75,"$50-75")])

    lines.append(f"\n{'─'*40}")
    lines.append("TOP WINNING TICKERS (most frequent)")
    lines.append(f"{'─'*40}")
    top = winners["ticker"].value_counts().head(15)
    for ticker, count in top.items():
        ticker_wins = winners[winners["ticker"] == ticker]
        avg_gain = ticker_wins["max_gain_session_pct"].mean()
        lines.append(f"  {ticker:8s}  {count:3d} winning signals  avg max gain: +{avg_gain:.1f}%")

    lines.append(f"\n{'─'*40}")
    lines.append("WORST LOSING TICKERS (most frequent)")
    lines.append(f"{'─'*40}")
    worst = losers["ticker"].value_counts().head(15)
    for ticker, count in worst.items():
        ticker_losses = losers[losers["ticker"] == ticker]
        avg_loss = ticker_losses["return_1h_pct"].mean()
        lines.append(f"  {ticker:8s}  {count:3d} losing signals   avg 1hr return: {avg_loss:.1f}%")

    lines.append(f"\n{'─'*40}")
    lines.append("RVOL SWEET SPOT ANALYSIS")
    lines.append(f"{'─'*40}")
    lines.append("Win rate by RVOL band (max session gain >= 5%):")
    for lo, hi in [(2,3),(3,5),(5,8),(8,15),(15,100)]:
        band = m1[(m1["rvol"] >= lo) & (m1["rvol"] < hi)]
        if band.empty:
            continue
        win_ct  = (band["max_gain_session_pct"] >= M1_WIN_THRESHOLD).sum()
        win_rate = win_ct / len(band) * 100
        avg_gain = band["max_gain_session_pct"].mean()
        lines.append(f"  RVOL {lo}-{hi}x:  {len(band):5d} signals  "
                     f"win rate {win_rate:4.0f}%  avg max gain {avg_gain:+.2f}%"
                     + ("  << best band" if win_rate > 25 else ""))

    lines.append(f"\n{'─'*40}")
    lines.append("MOVE SIZE SWEET SPOT ANALYSIS")
    lines.append(f"{'─'*40}")
    lines.append("Win rate by % from open at signal time:")
    for lo, hi in [(3,4),(4,5),(5,7),(7,10),(10,15),(15,100)]:
        band = m1[(m1["pct_from_open"] >= lo) & (m1["pct_from_open"] < hi)]
        if band.empty:
            continue
        win_ct   = (band["max_gain_session_pct"] >= M1_WIN_THRESHOLD).sum()
        win_rate = win_ct / len(band) * 100
        avg_gain = band["max_gain_session_pct"].mean()
        lines.append(f"  {lo}-{hi}% from open:  {len(band):5d} signals  "
                     f"win rate {win_rate:4.0f}%  avg max gain {avg_gain:+.2f}%"
                     + ("  << best band" if win_rate > 25 else ""))


def analyse_m2(df, lines):
    lines.append("\n\n" + "=" * 60)
    lines.append("MODE 2 — SUPPORT BOUNCE: WINNER vs LOSER ANALYSIS")
    lines.append("=" * 60)

    m2 = df[df["mode"] == "SUPPORT_BOUNCE"].copy()
    if m2.empty or "return_3d_pct" not in m2.columns:
        lines.append("No support bounce signals or 3d return column missing.")
        return

    winners = m2[m2["return_3d_pct"] >= M2_WIN_THRESHOLD]
    losers  = m2[m2["return_3d_pct"] <= M2_LOSS_THRESHOLD]

    lines.append(f"\nTotal support bounce signals: {len(m2)}")
    lines.append(f"Winners (3d return >= {M2_WIN_THRESHOLD}%): {len(winners)} "
                 f"({len(winners)/len(m2)*100:.0f}%)")
    lines.append(f"Losers  (3d return <= {M2_LOSS_THRESHOLD}%): {len(losers)} "
                 f"({len(losers)/len(m2)*100:.0f}%)")

    if winners.empty or losers.empty:
        lines.append("Not enough data to compare.")
        return

    lines.append(f"\n{'─'*40}")
    lines.append("SIGNAL CHARACTERISTICS")
    lines.append(f"{'─'*40}")

    compare_groups(winners, losers, "level_touches", "Touch count", lines,
                   bins=[(3,4,"3 touches"), (4,5,"4 touches"), (5,8,"5-7 touches"),
                         (8,100,"8+ touches")])

    compare_groups(winners, losers, "dist_pct", "Distance from level (%)", lines,
                   bins=[(0,0.5,"0-0.5%"), (0.5,1,"0.5-1%"), (1,2,"1-2%"), (2,3,"2-3%")])

    compare_groups(winners, losers, "atr", "ATR at time of signal", lines)

    compare_groups(winners, losers, "score", "Scanner score", lines)

    lines.append(f"\n{'─'*40}")
    lines.append("DISTANCE FROM LEVEL — KEY QUESTION")
    lines.append("Does entering closer to the level improve outcomes?")
    lines.append(f"{'─'*40}")
    for lo, hi in [(0,0.5),(0.5,1.0),(1.0,1.5),(1.5,2.0),(2.0,3.0)]:
        band = m2[(m2["dist_pct"] >= lo) & (m2["dist_pct"] < hi)]
        if band.empty:
            continue
        w = (band["return_3d_pct"] >= M2_WIN_THRESHOLD).sum()
        l = (band["return_3d_pct"] <= M2_LOSS_THRESHOLD).sum()
        avg = band["return_3d_pct"].mean()
        stop = band.get("stop_hit_3d", pd.Series()).sum() if "stop_hit_3d" in band.columns else "n/a"
        lines.append(f"  {lo:.1f}-{hi:.1f}% away: {len(band):5d} signals  "
                     f"avg 3d {avg:+.2f}%  wins {w}  losses {l}"
                     + ("  << enter here" if avg > 2 else ""))

    lines.append(f"\n{'─'*40}")
    lines.append("TOUCH COUNT DETAIL")
    lines.append(f"{'─'*40}")
    for t in range(3, 10):
        band = m2[m2["level_touches"] == t]
        if len(band) < 10:
            continue
        avg  = band["return_3d_pct"].mean()
        wct  = (band["return_3d_pct"] >= M2_WIN_THRESHOLD).sum()
        lct  = (band["return_3d_pct"] <= M2_LOSS_THRESHOLD).sum()
        lines.append(f"  {t} touches: {len(band):5d} signals  avg 3d {avg:+.2f}%  "
                     f"wins {wct}  losses {lct}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print("Loading backtest results...")
    df = load()
    print(f"Loaded {len(df)} signals\n")

    lines = []
    lines.append("=" * 60)
    lines.append("GarAI Intraday Scanner — Winner Analysis")
    lines.append(f"Source: {INPUT_FILE}  ({len(df)} total signals)")
    lines.append("=" * 60)
    lines.append(f"\nMode 1 win = max session gain >= {M1_WIN_THRESHOLD}%")
    lines.append(f"Mode 1 loss = 1hr return <= {M1_LOSS_THRESHOLD}%")
    lines.append(f"Mode 2 win = 3d return >= {M2_WIN_THRESHOLD}%")
    lines.append(f"Mode 2 loss = 3d return <= {M2_LOSS_THRESHOLD}%")

    analyse_m1(df, lines)
    analyse_m2(df, lines)

    lines.append("\n\n" + "=" * 60)
    lines.append("WHAT TO DO WITH THESE FINDINGS")
    lines.append("=" * 60)
    lines.append("""
The numbers above answer one question: what did the winning
signals have in common that the losers didn't?

Look for:
  - An RVOL band where win rate jumps meaningfully (>25%)
  - A move size band where outcomes are clearly better
  - A time of day where win rate is consistently above 55%
  - A price range that produces better results
  - Touch counts for Mode 2 where average return is highest

Any finding where winners and losers differ by more than 10
percentage points is worth acting on. Add it as a filter in
scanner.py and re-run the backtest to measure the impact.
""")

    output = "\n".join(lines)
    print(output)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
