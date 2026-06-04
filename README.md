# GarAI Intraday Scanner

**Live intraday momentum and support/resistance scanner for US stocks.**

Built by Gary Stow. Part of the GarAI trading project. Companion to the [GarAI Momentum Scanner](https://github.com/GarySto/market-universe-generator) (premarket).

---

## What it does

Scans up to 400 US stocks every 30 minutes during NYSE market hours (14:30–21:00 BST) and surfaces two types of trade setup:

**Mode 1 — Momentum continuation**
Stocks showing accelerating intraday price movement with above-average volume. Same-day exit before 21:00 BST close.

**Mode 2 — Support / resistance level plays**
Stocks approaching a horizontal price level that has been tested two or more times over the past 6 months. Can be held multi-day. Every candidate includes an ATR-grounded stop-loss with the full calculation logged for later review.

---

## Live dashboard

[garai-intraday.streamlit.app](https://garai-intraday.streamlit.app)

---

## Scoring

### Mode 1 — Momentum signals (max score 10)

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Price change from open | Up to 5 pts | Raw directional momentum |
| Intraday RVOL | Up to 3 pts | Volume vs time-adjusted daily average |
| Slope (acceleration) | 2 pts | Last 3 candles trending up = still moving |

Minimum thresholds: 1.5% move from open AND RVOL ≥ 1.5×

### Mode 2 — Level signals (max score 9)

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Proximity to level | Up to 5 pts | Closer = higher score |
| Touch count | Up to 4 pts | More touches = stronger level |

Minimum: level must have been tested 2+ times within ±1.5% price band over 6 months

### Stop-loss calculation (Mode 2)

```
stop_loss = lowest_price_at_level − (0.5 × ATR14)
```

ATR (Average True Range) is stock-specific — a volatile stock gets a wider buffer than a stable one. The full reasoning is logged to CSV on every scan so results can be reviewed over time.

---

## Architecture

```
tickers.txt          → watchlist (Trading 212 universe)
scanner.py           → scoring engine (Mode 1 + Mode 2)
output/intraday.csv  → results (updated every 30 mins)
streamlit_app.py     → live dashboard
.github/workflows/   → GitHub Actions schedule
```

**Schedule:** Every 30 minutes, 13:30–20:30 UTC (Mon–Fri). GitHub Actions can run up to 15 minutes late, hence the early start and late end buffer.

**Data source:** yfinance — 6 months daily OHLCV for level detection, 5-minute intraday candles for momentum scoring.

---

## Tech stack

| Component | Tool |
|-----------|------|
| Language | Python 3.11 |
| Data | yfinance |
| Processing | pandas, numpy, pytz |
| Dashboard | Streamlit |
| Automation | GitHub Actions (free tier) |
| Hosting | Streamlit Cloud (free tier) |
| Total cost | £0 |

---

## Related projects

- [GarAI Momentum Scanner](https://github.com/GarySto/market-universe-generator) — premarket gap scanner, runs before NYSE open
- [Portfolio](https://garysto.github.io) — project documentation and context

---

*Not financial advice. Real money, real rules, real data. A bloke in his early 40s learning to code and trade at the same time.*
