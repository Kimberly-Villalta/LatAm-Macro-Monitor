"""
LatAm Macro Monitor
A live dashboard tracking currencies, commodities, rates, inflation, sovereign
risk, and the global funding channel across Brazil, Mexico, Colombia, and Chile.

Institutional-grade analyst dashboard.

Data sources (all free, no Bloomberg):
  - yfinance:    FX, commodities, US Treasury yields, DXY, ETFs, equity indices
  - BCB SGS API: Brazil Selic target and IPCA inflation

Author: Kimberly Villalta
"""

import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime
import plotly.graph_objects as go
import numpy as np

# ============================================================================
# PAGE CONFIG & INSTITUTIONAL STYLING
# ============================================================================
st.set_page_config(page_title="LatAm Macro Monitor", layout="wide")

st.markdown(
    """
    <style>
        :root {
            --primary-dark: #1a1a1a;
            --secondary-gray: #6b7280;
            --accent-blue: #0052cc;
            --border-light: #e5e7eb;
        }
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 3.5rem;
            max-width: 1300px;
        }
        h1 {
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 2.1rem; font-weight: 600;
            letter-spacing: -0.6px; color: var(--primary-dark);
            margin-bottom: 0.3rem;
        }
        h2 {
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 1.35rem; font-weight: 600; color: var(--primary-dark);
            margin-top: 1.8rem; margin-bottom: 0.6rem; letter-spacing: -0.4px;
        }
        h3 {
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 1.05rem; font-weight: 600; color: var(--primary-dark);
            margin-top: 1rem;
        }
        /* Metric cards: give titles room so they never clip to "TE" */
        [data-testid="stMetric"] {
            background: transparent;
            border: 1px solid var(--border-light);
            padding: 1.1rem 1.3rem;
            border-radius: 3px;
            box-shadow: none;
            min-height: 7rem;
        }
        [data-testid="stMetricLabel"] {
            color: var(--secondary-gray);
            font-size: 0.78rem; font-weight: 600;
            letter-spacing: 0.4px; text-transform: uppercase;
            white-space: normal; overflow: visible;
        }
        [data-testid="stMetricLabel"] p { white-space: normal; overflow: visible; }
        [data-testid="stMetricValue"] {
            color: var(--primary-dark);
            font-size: 1.55rem; font-weight: 600;
            font-family: 'Courier New', monospace;
        }
        .stCaption { color: var(--secondary-gray); font-size: 0.8rem; }
        .section-note {
            color: var(--secondary-gray); font-size: 0.875rem;
            margin-bottom: 1.2rem; font-weight: 400; line-height: 1.5;
            padding-right: 1rem;
        }
        .source-note {
            color: #9ca3af; font-size: 0.75rem; line-height: 1.7;
            font-weight: 400; margin-top: 1.5rem;
        }
        hr { border: none; border-top: 1px solid var(--border-light);
             margin: 2.5rem 0; opacity: 0.6; }
        [role="radiogroup"] { gap: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
# FX tickers are quoted as LOCAL CURRENCY per USD (e.g. BRL/USD ~ 5.0).
# A rising line therefore means local-currency DEPRECIATION.
COUNTRIES = {
    "Brazil":   {"fx": "USDBRL=X", "equity": "^BVSP", "flag": "BR", "code": "BRL"},
    "Mexico":   {"fx": "USDMXN=X", "equity": "^MXX",  "flag": "MX", "code": "MXN"},
    "Colombia": {"fx": "USDCOP=X", "equity": None,    "flag": "CO", "code": "COP"},
    "Chile":    {"fx": "USDCLP=X", "equity": None,    "flag": "CL", "code": "CLP"},
}

COMMODITIES = {
    "Brent crude":  {"ticker": "BZ=F", "unit": "$/bbl"},
    "WTI crude":    {"ticker": "CL=F", "unit": "$/bbl"},
    "Copper":       {"ticker": "HG=F", "unit": "$/lb"},
    "Soybeans":     {"ticker": "ZS=F", "unit": "c/bu"},
}
BASKET_COMPONENTS = {"Oil (Brent)": "BZ=F", "Copper": "HG=F", "Soybeans": "ZS=F"}

# Global funding channel: the other side of the Campello equation.
FUNDING = {
    "US 2Y Treasury":  {"ticker": "^IRX", "alt": "2YY=F", "unit": "%"},
    "US 10Y Treasury": {"ticker": "^TNX", "unit": "%"},
    "Dollar Index":    {"ticker": "DX-Y.NYB", "unit": "DXY"},
}

COLORS = {
    "blue":   "#0052cc",
    "orange": "#d97706",
    "green":  "#059669",
    "red":    "#dc2626",
    "gray":   "#6b7280",
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}

BASE_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="system-ui, -apple-system, sans-serif", size=11),
    hovermode="x unified",
)

# ============================================================================
# DATA FETCHERS
# ============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yf_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Daily close history for a yfinance ticker. Empty df on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty:
            return pd.DataFrame()
        out = df[["Close"]].rename(columns={"Close": ticker})
        out.index = pd.to_datetime(out.index).tz_localize(None)
        return out
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bcb_series(code: int, years: int = 3) -> pd.DataFrame:
    """Banco Central do Brasil SGS series (no API key needed)."""
    end = datetime.today()
    start = end.replace(year=end.year - years)
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
        f"?formato=json&dataInicial={start:%d/%m/%Y}&dataFinal={end:%d/%m/%Y}"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        df = pd.DataFrame(r.json())
        df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
        return df.set_index("data")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred_series(series_id: str, years: int = 2) -> pd.DataFrame:
    """
    Fetch a FRED series (e.g. DGS2 = 2Y Treasury constant maturity) as a
    single-column daily dataframe already expressed in percent. Returns an
    empty df if no key is configured or the request fails, so the app degrades
    gracefully to the Yahoo proxy.
    """
    key = st.secrets.get("FRED_API_KEY", "") if hasattr(st, "secrets") else ""
    if not key:
        return pd.DataFrame()
    end = datetime.today()
    start = end.replace(year=end.year - years)
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={key}&file_type=json"
        f"&observation_start={start:%Y-%m-%d}&observation_end={end:%Y-%m-%d}"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            return pd.DataFrame()
        df = pd.DataFrame(obs)[["date", "value"]]
        df["date"] = pd.to_datetime(df["date"])
        # FRED uses "." for missing values; coerce and drop.
        df[series_id] = pd.to_numeric(df["value"], errors="coerce")
        return df.set_index("date")[[series_id]].dropna()
    except Exception:
        return pd.DataFrame()


# ============================================================================
# HELPERS
# ============================================================================
PERIOD_DAYS = {"1M": 30, "3M": 90, "6M": 180, "1Y": 366}


def slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty:
        return df
    end = df.index.max()
    if period == "YTD":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    else:
        start = end - pd.Timedelta(days=PERIOD_DAYS.get(period, 366))
    return df[df.index >= start]


def latest_and_change(df: pd.DataFrame, col: str):
    if df.empty or col not in df.columns:
        return None, None, None
    s = df[col].dropna()
    if len(s) < 2:
        return (s.iloc[-1] if len(s) else None), None, None
    latest = s.iloc[-1]
    daily = (s.iloc[-1] / s.iloc[-2] - 1) * 100
    window = (s.iloc[-1] / s.iloc[0] - 1) * 100
    return latest, daily, window


def index_to_100(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        s = df[col].dropna()
        if not s.empty:
            out[col] = df[col] / s.iloc[0] * 100
    return out


def align_corr(s1: pd.Series, s2: pd.Series):
    """Align two daily series on common dates and return Pearson r on levels."""
    joined = pd.concat([s1, s2], axis=1).dropna()
    if len(joined) < 3:
        return None
    return joined.iloc[:, 0].corr(joined.iloc[:, 1])


# ============================================================================
# HEADER & CONTROLS
# ============================================================================
st.title("LatAm Macro Monitor")

fx_raw = {c: fetch_yf_history(m["fx"]) for c, m in COUNTRIES.items()}
as_of = max([df.index.max() for df in fx_raw.values() if not df.empty], default=None)
as_of_str = f"{as_of:%b %d, %Y}" if as_of is not None else "unavailable"
st.caption(
    f"Currencies, commodities, rates, sovereign risk, and the global funding channel  ·  Data as of {as_of_str}"
)

period = st.radio(
    "Lookback window",
    options=["1M", "3M", "6M", "YTD", "1Y"],
    index=4,
    horizontal=True,
)

st.markdown("---")

# ============================================================================
# SECTION 1: CURRENCIES VS USD
# ============================================================================
st.markdown("## Currencies vs. USD")
st.markdown(
    "<div class='section-note'>Quoted as local currency per USD (e.g. BRL/USD around 5.0). "
    "A rising line signals local-currency depreciation, that is, weakness.</div>",
    unsafe_allow_html=True,
)

fx_cols = st.columns(len(COUNTRIES))
fx_sliced = {}
for (country, meta), col in zip(COUNTRIES.items(), fx_cols):
    sl = slice_period(fx_raw[country], period)
    fx_sliced[country] = sl
    latest, daily, _ = latest_and_change(sl, meta["fx"])
    with col:
        if latest is not None:
            st.metric(
                f"{country} ({meta['code']}/USD)",
                f"{latest:,.2f}",
                f"{daily:+.2f}% d/d" if daily is not None else "n/a",
                delta_color="inverse",  # weaker FX (up) is "bad" -> red
            )
        else:
            st.metric(f"{country} ({meta['code']}/USD)", "n/a", "data unavailable")

fx_combined = pd.concat([df for df in fx_sliced.values() if not df.empty], axis=1).sort_index()
if not fx_combined.empty:
    fx_indexed = index_to_100(fx_combined)
    names = {meta["fx"]: f"{c} ({meta['code']}/USD)" for c, meta in COUNTRIES.items()}
    palette = [COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["red"]]
    fig = go.Figure()
    for i, col in enumerate(fx_indexed.columns):
        s = fx_indexed[col].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=names.get(col, col),
            line=dict(width=2.4, color=palette[i % len(palette)]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(
        title=dict(text=f"FX performance, {period} (indexed to 100; higher = weaker local FX)",
                   font=dict(size=14, family="Georgia, serif")),
        height=380, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.14), **BASE_LAYOUT,
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("FX history temporarily unavailable. Yahoo may be rate-limiting; refresh shortly.")

st.markdown("---")

# ============================================================================
# SECTION 2: GLOBAL FUNDING CHANNEL  (the other side of Campello)
# ============================================================================
st.markdown("## Global Funding Channel")
st.markdown(
    "<div class='section-note'>The financing side of the external constraint. Higher US yields and a stronger dollar "
    "tighten global funding and pull capital out of EM, neutralizing commodity-dollar inflows. "
    "US 2Y and 10Y are quoted in percent; DXY is an index level.</div>",
    unsafe_allow_html=True,
)

# ^TNX and ^IRX report yields x10 on Yahoo (e.g. 41.8 = 4.18%); divide by 10.
def fetch_yield_yahoo(ticker: str) -> pd.DataFrame:
    df = fetch_yf_history(ticker)
    if not df.empty:
        df[df.columns[0]] = df[df.columns[0]] / 10.0
    return df

# Prefer FRED constant-maturity yields (DGS2 = true 2Y, DGS10 = 10Y), already
# in percent. Fall back to the Yahoo proxy if no FRED key is configured.
fred_2y = fetch_fred_series("DGS2")
fred_10y = fetch_fred_series("DGS10")

if not fred_2y.empty:
    us2y = fred_2y
    us2y_label = "US 2Y Treasury"
    yield_source = "FRED constant-maturity (DGS2/DGS10)"
else:
    us2y = fetch_yield_yahoo("^IRX")  # 13-week bill proxy for the short end
    us2y_label = "US short rate (13w proxy)"
    yield_source = "Yahoo ^IRX/^TNX proxy"

if not fred_10y.empty:
    us10y = fred_10y
else:
    us10y = fetch_yield_yahoo("^TNX")

dxy = fetch_yf_history("DX-Y.NYB")

fund_cols = st.columns(3)
for col, (label, df, fmt) in zip(
    fund_cols,
    [(us2y_label, us2y, "{:.2f}%"),
     ("US 10Y Treasury", us10y, "{:.2f}%"),
     ("Dollar Index (DXY)", dxy, "{:.2f}")],
):
    sl = slice_period(df, period)
    latest, daily, _ = latest_and_change(sl, df.columns[0]) if not df.empty else (None, None, None)
    with col:
        if latest is not None:
            st.metric(label, fmt.format(latest),
                      f"{daily:+.2f}% d/d" if daily is not None else "n/a")
        else:
            st.metric(label, "n/a", "data unavailable")

# US yields on left axis, DXY on right axis. Both are levels, units shown on each axis.
us2y_s = slice_period(us2y, period)
us10y_s = slice_period(us10y, period)
dxy_s = slice_period(dxy, period)

if not us2y_s.empty or not us10y_s.empty or not dxy_s.empty:
    fig_fund = go.Figure()
    if not us2y_s.empty:
        s = us2y_s.iloc[:, 0].dropna()
        fig_fund.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=f"{us2y_label} (%)",
            line=dict(width=2.4, color=COLORS["blue"]), yaxis="y1",
            hovertemplate="%{y:.2f}%<extra>" + us2y_label + "</extra>",
        ))
    if not us10y_s.empty:
        s = us10y_s.iloc[:, 0].dropna()
        fig_fund.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name="US 10Y yield (%)",
            line=dict(width=2.4, color=COLORS["green"]), yaxis="y1",
            hovertemplate="%{y:.2f}%<extra>US 10Y</extra>",
        ))
    if not dxy_s.empty:
        s = dxy_s.iloc[:, 0].dropna()
        fig_fund.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name="DXY (index)",
            line=dict(width=2.4, color=COLORS["red"], dash="dash"), yaxis="y2",
            hovertemplate="%{y:.2f}<extra>DXY</extra>",
        ))
    fig_fund.update_layout(
        title=dict(text=f"US yields and the dollar, {period}",
                   font=dict(size=14, family="Georgia, serif")),
        height=400, margin=dict(l=55, r=55, t=50, b=10),
        legend=dict(orientation="h", y=-0.16),
        yaxis=dict(title="US Treasury yield (%)"),
        yaxis2=dict(title="DXY (index)", overlaying="y", side="right"),
        **BASE_LAYOUT,
    )
    st.plotly_chart(fig_fund, use_container_width=True, config=PLOTLY_CONFIG)
    st.markdown(
        f"<div class='section-note'><i>When the 2Y holds near or above 4% and DXY stays firm, the funding channel "
        f"stays restrictive. That is the financial-account pressure that offsets the trade-account windfall. "
        f"Yield source: {yield_source}.</i></div>",
        unsafe_allow_html=True,
    )
else:
    st.info("Funding-channel data temporarily unavailable.")

st.markdown("---")

# ============================================================================
# SECTION 3: EXPORT COMMODITIES & TRANSMISSION  (indexed, with correlation)
# ============================================================================
st.markdown("## Export Commodities and Currency Transmission")
st.markdown(
    "<div class='section-note'>Oil, copper, and soy generate the region's export dollars. The dual-axis chart compares "
    "Brent against the BRL terms-of-trade-implied path; both series are indexed to 100 so the comparison is fair, and a "
    "rolling correlation is reported to quantify any decoupling.</div>",
    unsafe_allow_html=True,
)

cmdty_raw = {name: fetch_yf_history(m["ticker"]) for name, m in COMMODITIES.items()}
cmdty_cols = st.columns(len(COMMODITIES))
for (name, meta), col in zip(COMMODITIES.items(), cmdty_cols):
    sl = slice_period(cmdty_raw[name], period)
    latest, _, window = latest_and_change(sl, meta["ticker"])
    with col:
        if latest is not None:
            st.metric(f"{name} ({meta['unit']})", f"{latest:,.2f}",
                      f"{window:+.1f}% {period}" if window is not None else "n/a")
        else:
            st.metric(f"{name} ({meta['unit']})", "n/a", "unavailable")

brent_s = slice_period(cmdty_raw["Brent crude"], period)
brl_s = slice_period(fx_raw["Brazil"], period)

if not brent_s.empty and not brl_s.empty:
    # Both indexed to 100 so neither axis can be scaled to fake a correlation.
    brent_idx = index_to_100(brent_s).iloc[:, 0].dropna()
    # For terms-of-trade logic, invert BRL/USD so "up = stronger BRL" lines up with "up = higher Brent".
    brl_levels = brl_s.iloc[:, 0].dropna()
    brl_strength = (1.0 / brl_levels)
    brl_strength_idx = (brl_strength / brl_strength.iloc[0] * 100)

    r = align_corr(brent_idx, brl_strength_idx)
    r_txt = f"  ·  Pearson r = {r:+.2f}" if r is not None else ""

    fig_tx = go.Figure()
    fig_tx.add_trace(go.Scatter(
        x=brent_idx.index, y=brent_idx.values, mode="lines",
        name="Brent crude (supply channel)",
        line=dict(width=2.5, color=COLORS["orange"]),
        hovertemplate="%{y:.1f}<extra>Brent</extra>",
    ))
    fig_tx.add_trace(go.Scatter(
        x=brl_strength_idx.index, y=brl_strength_idx.values, mode="lines",
        name="BRL strength (terms-of-trade implied path)",
        line=dict(width=2.5, color=COLORS["blue"], dash="dash"),
        hovertemplate="%{y:.1f}<extra>BRL strength</extra>",
    ))
    fig_tx.update_layout(
        title=dict(text=f"Commodity supply vs. currency strength, {period} (both indexed to 100){r_txt}",
                   font=dict(size=14, family="Georgia, serif")),
        height=390, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.14), **BASE_LAYOUT,
    )
    st.plotly_chart(fig_tx, use_container_width=True, config=PLOTLY_CONFIG)
    st.markdown(
        "<div class='section-note'><i>Both series indexed to 100 at window start; BRL is shown as strength "
        "(inverse of BRL/USD) so it is directionally comparable to Brent. A low or negative correlation while Brent "
        "rallies is the visual signature of the capital-account drain overwhelming the terms-of-trade windfall.</i></div>",
        unsafe_allow_html=True,
    )

# Export basket, indexed
basket_parts = []
for label, ticker in BASKET_COMPONENTS.items():
    sl = slice_period(fetch_yf_history(ticker), period)
    if not sl.empty:
        s = sl[ticker].dropna()
        if not s.empty:
            basket_parts.append((s / s.iloc[0] * 100).rename(label))

if basket_parts:
    basket = pd.concat(basket_parts, axis=1).sort_index()
    basket_avg = basket.mean(axis=1)
    comp_colors = [COLORS["orange"], COLORS["green"], COLORS["gray"]]
    fig_b = go.Figure()
    for i, col in enumerate(basket.columns):
        s = basket[col].dropna()
        fig_b.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=col,
            line=dict(width=1.8, color=comp_colors[i % len(comp_colors)]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    fig_b.add_trace(go.Scatter(
        x=basket_avg.index, y=basket_avg.values, mode="lines",
        name="LatAm Export Basket",
        line=dict(width=3, color=COLORS["blue"]),
        hovertemplate="%{y:.1f}<extra>LatAm Export Basket</extra>",
    ))
    fig_b.update_layout(
        title=dict(text=f"LatAm export-commodity basket, {period} (indexed, equal-weighted)",
                   font=dict(size=14, family="Georgia, serif")),
        height=340, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.14), **BASE_LAYOUT,
    )
    st.plotly_chart(fig_b, use_container_width=True, config=PLOTLY_CONFIG)

st.markdown("---")

# ============================================================================
# SECTION 4: BRAZIL RATES, INFLATION, AND REAL RATE  (fixed)
# ============================================================================
st.markdown("## Brazil: Policy Rate, Inflation, and the Real Rate")
st.markdown(
    "<div class='section-note'>The real rate (Selic minus IPCA) is the true cost of capital for borrowers and the "
    "clearest read on how restrictive policy is. A high, sticky real rate is the domestic symptom of the external "
    "constraint.</div>",
    unsafe_allow_html=True,
)

selic = fetch_bcb_series(432)     # daily Selic target
ipca12 = fetch_bcb_series(13522)  # IPCA 12m accumulated

c1, c2, c3 = st.columns(3)

with c1:
    if not selic.empty:
        st.metric("Selic Policy Rate", f"{selic['valor'].iloc[-1]:.2f}%", "Target, % p.a.")
    else:
        st.metric("Selic Policy Rate", "n/a", "unavailable")
with c2:
    if not ipca12.empty:
        st.metric("IPCA Inflation (12m)", f"{ipca12['valor'].iloc[-1]:.2f}%", "YoY")
    else:
        st.metric("IPCA Inflation (12m)", "n/a", "unavailable")
with c3:
    if not selic.empty and not ipca12.empty:
        rr_now = selic["valor"].iloc[-1] - ipca12["valor"].iloc[-1]
        st.metric("Real Rate (Selic - IPCA)", f"{rr_now:.2f}%", "Ex-post, % p.a.")
    else:
        st.metric("Real Rate (Selic - IPCA)", "n/a", "unavailable")

# Build a properly aligned real-rate series so the chart is never a flat zero line.
if not selic.empty and not ipca12.empty:
    s_selic = selic["valor"].rename("Selic")
    s_ipca = ipca12["valor"].rename("IPCA")
    merged = pd.concat([s_selic, s_ipca], axis=1).sort_index()
    # IPCA is monthly, Selic is daily; forward-fill IPCA onto the daily index.
    merged["IPCA"] = merged["IPCA"].ffill()
    merged = merged.dropna()
    merged["Real_Rate"] = merged["Selic"] - merged["IPCA"]
    rr = slice_period(merged[["Real_Rate"]], period)

    fig_rr = go.Figure()
    fig_rr.add_trace(go.Scatter(
        x=rr.index, y=rr["Real_Rate"], mode="lines", name="Real rate",
        fill="tozeroy", line=dict(width=2.5, color=COLORS["green"]),
        hovertemplate="%{y:.2f}%<extra>Real rate</extra>",
    ))
    fig_rr.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_rr.update_layout(
        title=dict(text=f"Brazil ex-post real policy rate, {period} (Selic minus IPCA 12m)",
                   font=dict(size=14, family="Georgia, serif")),
        height=340, margin=dict(l=10, r=10, t=50, b=10),
        yaxis_title="% p.a.", **BASE_LAYOUT,
    )
    st.plotly_chart(fig_rr, use_container_width=True, config=PLOTLY_CONFIG)

    # Selic and IPCA levels together for context.
    levels = slice_period(merged[["Selic", "IPCA"]], period)
    fig_lvl = go.Figure()
    fig_lvl.add_trace(go.Scatter(
        x=levels.index, y=levels["Selic"], mode="lines", name="Selic (%)",
        line=dict(width=2.2, color=COLORS["blue"]),
        hovertemplate="%{y:.2f}%<extra>Selic</extra>",
    ))
    fig_lvl.add_trace(go.Scatter(
        x=levels.index, y=levels["IPCA"], mode="lines", name="IPCA 12m (%)",
        line=dict(width=2.2, color=COLORS["orange"]),
        hovertemplate="%{y:.2f}%<extra>IPCA 12m</extra>",
    ))
    fig_lvl.update_layout(
        title=dict(text=f"Selic vs. IPCA, {period}", font=dict(size=14, family="Georgia, serif")),
        height=320, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.16), yaxis_title="% p.a.", **BASE_LAYOUT,
    )
    st.plotly_chart(fig_lvl, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("Brazil rate/inflation series temporarily unavailable.")

st.markdown("---")

# ============================================================================
# SECTION 5: LATAM SOVEREIGN RISK PROXY
# ============================================================================
st.markdown("## LatAm Sovereign Risk Proxy")
st.markdown(
    "<div class='section-note'>Free real-time sovereign CDS is not publicly available, so risk is proxied two ways: "
    "the JPMorgan USD EM debt ETF (EMB) as a broad hard-currency benchmark, and 60-day annualized FX volatility for each "
    "LatAm currency as a market-priced country-stress gauge. FX vol is the cleaner LatAm-specific read; EMB is shown for "
    "context and is global, not LatAm-pure.</div>",
    unsafe_allow_html=True,
)

# FX realized volatility per country (annualized, 60-day rolling), in percent.
fig_vol = go.Figure()
vol_palette = [COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["red"]]
any_vol = False
for i, (country, meta) in enumerate(COUNTRIES.items()):
    sl = slice_period(fx_raw[country], period)
    if sl.empty:
        continue
    s = sl.iloc[:, 0].dropna()
    rets = np.log(s / s.shift(1)).dropna()
    vol = rets.rolling(60).std() * np.sqrt(252) * 100
    vol = vol.dropna()
    if vol.empty:
        continue
    any_vol = True
    fig_vol.add_trace(go.Scatter(
        x=vol.index, y=vol.values, mode="lines", name=f"{country} {meta['code']}",
        line=dict(width=2.2, color=vol_palette[i % len(vol_palette)]),
        hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>",
    ))
if any_vol:
    fig_vol.update_layout(
        title=dict(text=f"LatAm FX realized volatility, {period} (60-day, annualized)",
                   font=dict(size=14, family="Georgia, serif")),
        height=360, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.14), yaxis_title="Annualized vol (%)",
        **BASE_LAYOUT,
    )
    st.plotly_chart(fig_vol, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("FX volatility series temporarily unavailable.")

# EMB context line
emb = slice_period(fetch_yf_history("EMB"), period)
if not emb.empty:
    emb_idx = index_to_100(emb)
    fig_emb = go.Figure()
    fig_emb.add_trace(go.Scatter(
        x=emb_idx.index, y=emb_idx.iloc[:, 0], mode="lines",
        name="EMB (USD EM sovereign debt)",
        line=dict(width=2.4, color=COLORS["gray"]),
        hovertemplate="%{y:.1f}<extra>EMB</extra>",
    ))
    fig_emb.update_layout(
        title=dict(text=f"EMB hard-currency EM debt benchmark, {period} (indexed; global, for context)",
                   font=dict(size=14, family="Georgia, serif")),
        height=300, margin=dict(l=10, r=10, t=50, b=10), **BASE_LAYOUT,
    )
    st.plotly_chart(fig_emb, use_container_width=True, config=PLOTLY_CONFIG)

st.markdown("---")

# ============================================================================
# SECTION 6: LOCAL EQUITY INDICES
# ============================================================================
st.markdown("## Local Equity Indices")
st.markdown(
    "<div class='section-note'>Equity-market resilience or weakness relative to macro stress. Brazil (Bovespa) and "
    "Mexico (IPC) shown; indexed to 100 at window start.</div>",
    unsafe_allow_html=True,
)

eq_raw = {c: fetch_yf_history(m["equity"]) for c, m in COUNTRIES.items() if m["equity"]}
eq_sliced = pd.concat(
    [slice_period(eq_raw[c], period) for c in eq_raw if not eq_raw[c].empty],
    axis=1,
).sort_index()

if not eq_sliced.empty:
    eq_idx = index_to_100(eq_sliced)
    names = {meta["equity"]: c for c, meta in COUNTRIES.items() if meta["equity"]}
    palette = [COLORS["blue"], COLORS["orange"]]
    fig_eq = go.Figure()
    for i, col in enumerate(eq_idx.columns):
        s = eq_idx[col].dropna()
        if s.empty:
            continue
        fig_eq.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=names.get(col, col),
            line=dict(width=2.4, color=palette[i % len(palette)]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    fig_eq.update_layout(
        title=dict(text=f"Equity performance, {period} (indexed to 100)",
                   font=dict(size=14, family="Georgia, serif")),
        height=360, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.14), **BASE_LAYOUT,
    )
    st.plotly_chart(fig_eq, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("Equity history temporarily unavailable.")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown(
    """
    <div class="source-note">
    <b>Sources:</b> Yahoo Finance (FX, commodities, DXY, EMB, equity indices),
    FRED (US Treasury constant-maturity yields DGS2 and DGS10, when an API key is configured; otherwise Yahoo
    ^IRX/^TNX proxies), Banco Central do Brasil SGS API (Selic series 432, IPCA series 13522).<br>
    <b>Methodology:</b> FX quoted as local currency per USD; a rising line is local-currency depreciation. Performance
    charts indexed to 100 at the start of the selected window. Brent vs. BRL is shown with both series indexed to 100
    and a Pearson correlation to avoid dual-axis distortion; BRL is plotted as strength (inverse of BRL/USD). Real rate
    is ex-post Selic minus IPCA 12m, with monthly IPCA forward-filled onto the daily Selic index. US 2Y and 10Y from
    FRED constant-maturity series where available, expressed in percent. Sovereign risk proxied via 60-day annualized
    FX volatility (LatAm-specific) and the EMB ETF (global hard-currency benchmark, shown for context only); free
    real-time sovereign CDS is not available.<br>
    <b>Disclaimer:</b> Data delayed and for research and educational purposes only. Not investment advice.
    </div>
    """,
    unsafe_allow_html=True,
)
