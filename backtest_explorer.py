"""
GarAI — Backtest Explorer
===========================
Drop this file into your garai-intraday-scanner repo root.

To add as a tab in your existing Streamlit app, add this to
your main streamlit_app.py:

    tab1, tab2, tab3 = st.tabs(["Momentum", "Levels", "Backtest Explorer"])
    with tab3:
        import backtest_explorer
        backtest_explorer.render()

Or run standalone:
    streamlit run backtest_explorer.py

Reads:  backtest_results.csv  (output of backtest_local.py)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

# ── Colours (consistent with GarAI style) ─────────────────────────────────────
C_PURPLE  = "#7F77DD"
C_TEAL    = "#1D9E75"
C_CORAL   = "#D85A30"
C_AMBER   = "#EF9F27"
C_BLUE    = "#378ADD"
C_GRAY    = "#888780"
C_GREEN   = "#639922"
C_PINK    = "#D4537E"

MODE_COLOURS = {
    "MODE1_MOMENTUM":     C_PURPLE,
    "SUPPORT_BOUNCE":     C_TEAL,
    "RESISTANCE_WARNING": C_CORAL,
}

REGIME_COLOURS = {
    "Bull":      C_GREEN,
    "Bear":      C_CORAL,
    "Volatile":  C_AMBER,
    "Crisis":    "#E24B4A",
    "Recovery":  C_BLUE,
    "Unknown":   C_GRAY,
    "Pre-data":  C_GRAY,
}

CSV_PATH = "backtest_results.csv"

# ── Data loading ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data():
    for path in [CSV_PATH, os.path.join("..", CSV_PATH)]:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=["date"])
            return df
    return None


def win_rate(series):
    valid = series.dropna()
    if len(valid) == 0:
        return None
    return round((valid > 0).mean() * 100, 1)


def avg_return(series):
    valid = series.dropna()
    if len(valid) == 0:
        return None
    return round(valid.mean(), 2)


# ── Small helper: metric card row ──────────────────────────────────────────────

def metric_row(items):
    """items = list of (label, value, delta=None)"""
    cols = st.columns(len(items))
    for col, (label, value, *delta) in zip(cols, items):
        col.metric(label, value, delta[0] if delta else None)


# ── Main render ────────────────────────────────────────────────────────────────

def render():
    st.markdown("## 📊 Backtest Explorer")
    st.markdown("*Reads from `backtest_results.csv` — re-run `backtest_local.py` to refresh*")

    df = load_data()

    if df is None:
        st.warning("No `backtest_results.csv` found. Run `backtest_local.py` first.")
        return

    if df.empty:
        st.warning("CSV is empty.")
        return

    # ── Sidebar filters ────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🔎 Filters")

        modes_available = df["mode"].unique().tolist()
        selected_modes = st.multiselect(
            "Mode",
            modes_available,
            default=modes_available,
        )

        if "market_regime" in df.columns:
            regimes = ["All"] + sorted(df["market_regime"].dropna().unique().tolist())
            selected_regime = st.selectbox("Market regime", regimes)
        else:
            selected_regime = "All"

        if "date" in df.columns:
            min_date = df["date"].min().date()
            max_date = df["date"].max().date()
            date_range = st.date_input(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
        else:
            date_range = None

        if "rsi_at_signal" in df.columns:
            rsi_filter = st.slider("RSI at signal", 0, 100, (0, 100))
        else:
            rsi_filter = None

        st.markdown("---")
        st.caption(f"Total signals in CSV: **{len(df):,}**")

    # ── Apply filters ──────────────────────────────────────────────────────────
    fdf = df[df["mode"].isin(selected_modes)].copy()

    if selected_regime != "All" and "market_regime" in fdf.columns:
        fdf = fdf[fdf["market_regime"] == selected_regime]

    if date_range and len(date_range) == 2 and "date" in fdf.columns:
        fdf = fdf[
            (fdf["date"].dt.date >= date_range[0]) &
            (fdf["date"].dt.date <= date_range[1])
        ]

    if rsi_filter and "rsi_at_signal" in fdf.columns:
        fdf = fdf[
            (fdf["rsi_at_signal"] >= rsi_filter[0]) &
            (fdf["rsi_at_signal"] <= rsi_filter[1])
        ]

    if fdf.empty:
        st.warning("No signals match current filters.")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — Top-level summary
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### Overview")

    m1  = fdf[fdf["mode"] == "MODE1_MOMENTUM"]
    m2  = fdf[fdf["mode"] == "SUPPORT_BOUNCE"]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total signals", f"{len(fdf):,}")
    col2.metric("Mode 1 signals", f"{len(m1):,}")
    col3.metric("Mode 2 signals", f"{len(m2):,}")

    m1_wr = win_rate(m1.get("return_1h_pct", pd.Series(dtype=float)))
    m2_wr = win_rate(m2.get("return_3d_pct", pd.Series(dtype=float)))
    col4.metric("Mode 1 win rate (1h)", f"{m1_wr}%" if m1_wr else "—")
    col5.metric("Mode 2 win rate (3d)", f"{m2_wr}%" if m2_wr else "—")

    # ── Signal count over time ─────────────────────────────────────────────────
    if "date" in fdf.columns:
        st.markdown("#### Signal volume over time")
        daily_counts = (
            fdf.groupby(["date", "mode"])
            .size()
            .reset_index(name="count")
        )
        fig = px.bar(
            daily_counts,
            x="date", y="count", color="mode",
            color_discrete_map=MODE_COLOURS,
            barmode="stack",
            labels={"date": "", "count": "Signals", "mode": "Mode"},
            height=260,
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=8, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
        st.plotly_chart(fig, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — Mode 1 deep dive
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### Mode 1 — Momentum")

    if m1.empty:
        st.info("No Mode 1 signals in current filter.")
    else:
        # Key metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Signals", f"{len(m1):,}")
        c1h = win_rate(m1.get("return_1h_pct", pd.Series(dtype=float)))
        c2.metric("Win rate 1h", f"{c1h}%" if c1h else "—")
        mg = avg_return(m1.get("max_gain_session_pct", pd.Series(dtype=float)))
        c3.metric("Avg max session gain", f"{mg:+.2f}%" if mg else "—")
        gt10 = int((m1.get("max_gain_session_pct", pd.Series(dtype=float)).dropna() > 10).sum())
        c4.metric("Signals hitting +10%", f"{gt10:,}")

        tab_ret, tab_rsi, tab_time = st.tabs(["Returns", "RSI analysis", "Time of day"])

        with tab_ret:
            hour_cols = [c for c in ["return_1h_pct", "return_2h_pct", "return_4h_pct", "return_eod_pct"] if c in m1.columns]
            if hour_cols:
                fig = go.Figure()
                labels = {"return_1h_pct": "1h", "return_2h_pct": "2h",
                          "return_4h_pct": "4h", "return_eod_pct": "EOD"}
                for col in hour_cols:
                    valid = m1[col].dropna()
                    fig.add_trace(go.Box(
                        y=valid,
                        name=labels.get(col, col),
                        marker_color=C_PURPLE,
                        boxmean=True,
                        showlegend=False,
                    ))
                fig.add_hline(y=0, line_dash="dot", line_color=C_GRAY, line_width=1)
                fig.update_layout(
                    height=320,
                    margin=dict(l=0, r=0, t=8, b=0),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="Return %",
                )
                fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
                st.plotly_chart(fig, use_container_width=True)

                # Win rate table by horizon
                rows = []
                for col in hour_cols:
                    valid = m1[col].dropna()
                    if not valid.empty:
                        rows.append({
                            "Horizon": labels.get(col, col),
                            "Signals": len(valid),
                            "Win rate": f"{win_rate(valid)}%",
                            "Avg return": f"{avg_return(valid):+.2f}%",
                            "Avg winner": f"{avg_return(valid[valid>0]):+.2f}%" if (valid>0).any() else "—",
                            "Avg loser": f"{avg_return(valid[valid<0]):+.2f}%" if (valid<0).any() else "—",
                        })
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with tab_rsi:
            if "rsi_at_signal" in m1.columns and m1["rsi_at_signal"].notna().any():
                bands = [(0, 30, "Oversold 0-30"), (30, 50, "Neutral 30-50"),
                         (50, 70, "Healthy 50-70"), (70, 100, "Overbought 70-100")]
                rsi_rows = []
                for lo, hi, label in bands:
                    band = m1[(m1["rsi_at_signal"] >= lo) & (m1["rsi_at_signal"] < hi)]
                    if not band.empty and "return_1h_pct" in band.columns:
                        valid = band["return_1h_pct"].dropna()
                        if not valid.empty:
                            rsi_rows.append({
                                "RSI band": label,
                                "Signals": len(band),
                                "Win rate": win_rate(valid),
                                "Avg return": avg_return(valid),
                            })

                if rsi_rows:
                    rsi_df = pd.DataFrame(rsi_rows)
                    fig = px.bar(
                        rsi_df, x="RSI band", y="Win rate",
                        color="Win rate",
                        color_continuous_scale=[[0, C_CORAL], [0.5, C_AMBER], [1, C_TEAL]],
                        text="Win rate",
                        height=300,
                    )
                    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                    fig.add_hline(y=50, line_dash="dot", line_color=C_GRAY, line_width=1,
                                  annotation_text="50% break-even", annotation_position="right")
                    fig.update_layout(
                        margin=dict(l=0, r=0, t=8, b=0),
                        showlegend=False,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        coloraxis_showscale=False,
                    )
                    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", title="Win rate %")
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(
                        rsi_df.style.format({"Win rate": "{:.1f}%", "Avg return": "{:+.2f}%"}),
                        use_container_width=True, hide_index=True
                    )
            else:
                st.info("No RSI data in results. Make sure technicals folder is populated.")

        with tab_time:
            if "scan_time" in m1.columns:
                m1_copy = m1.copy()
                m1_copy["hour"] = m1_copy["scan_time"].str.extract(r"(\d+):").astype(float)
                hour_stats = []
                for h in sorted(m1_copy["hour"].dropna().unique()):
                    grp = m1_copy[m1_copy["hour"] == h]
                    valid = grp["return_1h_pct"].dropna() if "return_1h_pct" in grp.columns else pd.Series(dtype=float)
                    if not valid.empty:
                        hour_stats.append({
                            "Hour (BST)": f"{int(h):02d}:00",
                            "Signals": len(grp),
                            "Win rate": win_rate(valid),
                            "Avg return": avg_return(valid),
                        })
                if hour_stats:
                    hdf = pd.DataFrame(hour_stats)
                    fig = px.bar(
                        hdf, x="Hour (BST)", y="Win rate",
                        color="Win rate",
                        color_continuous_scale=[[0, C_CORAL], [0.5, C_AMBER], [1, C_TEAL]],
                        text="Win rate",
                        height=300,
                    )
                    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                    fig.add_hline(y=50, line_dash="dot", line_color=C_GRAY, line_width=1)
                    fig.update_layout(
                        margin=dict(l=0, r=0, t=8, b=0),
                        showlegend=False,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        coloraxis_showscale=False,
                    )
                    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", title="Win rate %")
                    st.plotly_chart(fig, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — Mode 2 deep dive
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### Mode 2 — Support bounces")

    if m2.empty:
        st.info("No Mode 2 signals in current filter.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Signals", f"{len(m2):,}")
        wr3 = win_rate(m2.get("return_3d_pct", pd.Series(dtype=float)))
        c2.metric("Win rate 3d", f"{wr3}%" if wr3 else "—")
        ar3 = avg_return(m2.get("return_3d_pct", pd.Series(dtype=float)))
        c3.metric("Avg 3d return", f"{ar3:+.2f}%" if ar3 else "—")
        sh5 = m2.get("stop_hit_5d", pd.Series(dtype=float))
        sh_rate = f"{sh5.dropna().mean()*100:.1f}%" if sh5.notna().any() else "—"
        c4.metric("Stop hit 5d", sh_rate)
        ev = None
        if ar3 and wr3:
            wr = wr3 / 100
            al = abs(avg_return(m2["return_3d_pct"][m2["return_3d_pct"] < 0])) if (m2.get("return_3d_pct", pd.Series(dtype=float)) < 0).any() else 2.0
            ev = round(wr * ar3 - (1 - wr) * al, 2)
        c5.metric("Expected value/trade", f"{ev:+.2f}%" if ev else "—")

        tab_ret2, tab_regime, tab_touch = st.tabs(["Returns", "By regime", "Touch count"])

        with tab_ret2:
            day_cols = [c for c in ["return_1d_pct", "return_3d_pct", "return_5d_pct"] if c in m2.columns]
            if day_cols:
                fig = go.Figure()
                labels2 = {"return_1d_pct": "1 day", "return_3d_pct": "3 days", "return_5d_pct": "5 days"}
                for col in day_cols:
                    valid = m2[col].dropna()
                    fig.add_trace(go.Box(
                        y=valid, name=labels2.get(col, col),
                        marker_color=C_TEAL, boxmean=True, showlegend=False,
                    ))
                fig.add_hline(y=0, line_dash="dot", line_color=C_GRAY, line_width=1)
                fig.update_layout(
                    height=320,
                    margin=dict(l=0, r=0, t=8, b=0),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="Return %",
                )
                fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
                st.plotly_chart(fig, use_container_width=True)

                rows2 = []
                for col in day_cols:
                    valid = m2[col].dropna()
                    if not valid.empty:
                        sh_col = col.replace("return", "stop_hit").replace("_pct", "")
                        sh = m2[sh_col].dropna().mean() * 100 if sh_col in m2.columns and m2[sh_col].notna().any() else None
                        rows2.append({
                            "Horizon": labels2.get(col, col),
                            "Signals": len(valid),
                            "Win rate": f"{win_rate(valid)}%",
                            "Avg return": f"{avg_return(valid):+.2f}%",
                            "Stop hit": f"{sh:.1f}%" if sh else "—",
                        })
                if rows2:
                    st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)

        with tab_regime:
            if "market_regime" in m2.columns and m2["market_regime"].notna().any():
                regime_rows = []
                for regime in sorted(m2["market_regime"].unique()):
                    grp = m2[m2["market_regime"] == regime]
                    valid = grp["return_3d_pct"].dropna() if "return_3d_pct" in grp.columns else pd.Series(dtype=float)
                    if not valid.empty:
                        regime_rows.append({
                            "Regime": regime,
                            "Signals": len(grp),
                            "Win rate": win_rate(valid),
                            "Avg 3d return": avg_return(valid),
                        })
                if regime_rows:
                    rdf = pd.DataFrame(regime_rows).sort_values("Win rate", ascending=False)
                    colours = [REGIME_COLOURS.get(r, C_GRAY) for r in rdf["Regime"]]
                    fig = make_subplots(rows=1, cols=2, subplot_titles=("Win rate by regime", "Avg 3d return by regime"))
                    fig.add_trace(go.Bar(
                        x=rdf["Regime"], y=rdf["Win rate"],
                        marker_color=colours, showlegend=False,
                        text=rdf["Win rate"].apply(lambda x: f"{x:.1f}%"),
                        textposition="outside",
                    ), row=1, col=1)
                    fig.add_trace(go.Bar(
                        x=rdf["Regime"], y=rdf["Avg 3d return"],
                        marker_color=colours, showlegend=False,
                        text=rdf["Avg 3d return"].apply(lambda x: f"{x:+.2f}%"),
                        textposition="outside",
                    ), row=1, col=2)
                    fig.add_hline(y=50, line_dash="dot", line_color=C_GRAY, line_width=1, row=1, col=1)
                    fig.add_hline(y=0, line_dash="dot", line_color=C_GRAY, line_width=1, row=1, col=2)
                    fig.update_layout(
                        height=360,
                        margin=dict(l=0, r=0, t=30, b=0),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(
                        rdf.style.format({"Win rate": "{:.1f}%", "Avg 3d return": "{:+.2f}%"}),
                        use_container_width=True, hide_index=True
                    )
            else:
                st.info("No market regime data. Add market_events.csv and re-run backtest.")

        with tab_touch:
            if "level_touches" in m2.columns:
                touch_rows = []
                for t in sorted(m2["level_touches"].dropna().unique()):
                    grp = m2[m2["level_touches"] == t]
                    valid = grp["return_3d_pct"].dropna() if "return_3d_pct" in grp.columns else pd.Series(dtype=float)
                    if not valid.empty:
                        touch_rows.append({
                            "Touches": int(t),
                            "Signals": len(grp),
                            "Win rate": win_rate(valid),
                            "Avg 3d return": avg_return(valid),
                        })
                if touch_rows:
                    tdf = pd.DataFrame(touch_rows)
                    fig = px.bar(
                        tdf, x="Touches", y="Avg 3d return",
                        color="Win rate",
                        color_continuous_scale=[[0, C_CORAL], [0.5, C_AMBER], [1, C_TEAL]],
                        text="Avg 3d return",
                        height=300,
                    )
                    fig.update_traces(texttemplate="%{text:+.2f}%", textposition="outside")
                    fig.add_hline(y=0, line_dash="dot", line_color=C_GRAY, line_width=1)
                    fig.update_layout(
                        margin=dict(l=0, r=0, t=8, b=0),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        coloraxis_showscale=True,
                        coloraxis_colorbar_title="Win %",
                    )
                    fig.update_xaxes(dtick=1)
                    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", title="Avg 3d return %")
                    st.plotly_chart(fig, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — Regime overview (both modes)
    # ══════════════════════════════════════════════════════════════════════════
    if "market_regime" in fdf.columns and fdf["market_regime"].notna().any():
        st.markdown("---")
        st.markdown("### Market regime context")

        regime_dist = fdf["market_regime"].value_counts().reset_index()
        regime_dist.columns = ["Regime", "Signals"]
        colours_pie = [REGIME_COLOURS.get(r, C_GRAY) for r in regime_dist["Regime"]]

        col_pie, col_bar = st.columns(2)
        with col_pie:
            fig = px.pie(
                regime_dist, values="Signals", names="Regime",
                color="Regime",
                color_discrete_map=REGIME_COLOURS,
                hole=0.5,
                height=280,
            )
            fig.update_layout(
                margin=dict(l=0, r=0, t=8, b=0),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)

        with col_bar:
            if "event_name" in fdf.columns:
                top_events = (
                    fdf[fdf["event_name"] != "None"]["event_name"]
                    .value_counts()
                    .head(10)
                    .reset_index()
                )
                top_events.columns = ["Event", "Signals"]
                if not top_events.empty:
                    fig = px.bar(
                        top_events, x="Signals", y="Event",
                        orientation="h",
                        color_discrete_sequence=[C_AMBER],
                        height=280,
                    )
                    fig.update_layout(
                        margin=dict(l=0, r=0, t=8, b=0),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        yaxis=dict(autorange="reversed"),
                    )
                    fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)")
                    st.plotly_chart(fig, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — Raw data explorer
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    with st.expander("🔍 Raw signal data"):
        display_cols = [c for c in [
            "date", "scan_time", "ticker", "mode", "score",
            "pct_from_open", "rvol", "rsi_at_signal",
            "level_price", "level_touches",
            "return_1h_pct", "return_3d_pct",
            "stop_loss", "stop_hit_3d",
            "market_regime", "event_name",
            "entry_price",
        ] if c in fdf.columns]

        st.dataframe(
            fdf[display_cols].sort_values("date", ascending=False),
            use_container_width=True,
            height=400,
        )
        csv_export = fdf.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download filtered results as CSV",
            data=csv_export,
            file_name="backtest_filtered.csv",
            mime="text/csv",
        )


# ── Standalone entry point ─────────────────────────────────────────────────────
if __name__ == "__main__":
    st.set_page_config(
        page_title="GarAI Backtest Explorer",
        page_icon="📊",
        layout="wide",
    )
    render()
