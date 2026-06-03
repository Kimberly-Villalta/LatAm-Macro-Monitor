"""
LatAm Macro Monitor
A live dashboard tracking currencies, commodities, rates, inflation, and
sovereign risk across Brazil, Mexico, Colombia, and Chile.

Data sources (all free, no Bloomberg):
  - yfinance:    FX, commodities, sovereign-bond ETFs, local equity indices
  - BCB SGS API: Brazil Selic target and IPCA inflation (no key required)

Author: Kimberly Villalta
"""

import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# Page setup + styling
# -----------------------------------------------------------------------------
st.set_page_config(page_title="LatAm Macro Monitor", layout="wide")

st.markdown(
    """
    <style>
        .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
        h1, h2, h3 {font-family: 'Georgia', serif; letter-spacing: -0.4px;}
        h2 {font-size: 1.35rem; margin-top: 0.4rem;}
        .stMetric {background: rgba(140,140,140,0.06); padding: 0.6rem 0.8rem; border-radius: 6px;}
        .source-note {color: #8a8a8a; font-size: 0.78rem; line-height: 1.55;}
        .section-note {color: #9aa0a6; font-size: 0.86rem; margin-bottom: 0.4rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# Country labels. Flags are functional, used as fast scan labels for four markets.
COUNTRIES = {
    "Brazil":   {"fx": "USDBRL=X", "equity": "^BVSP", "flag": "🇧🇷", "code": "BRL"},
    "Mexico":   {"fx": "MXN=X", "equity": "^MXX",  "flag": "🇲🇽", "code": "MXN"},
    "Colombia": {"fx": "COP=X", "equity": None, ...},
    "Chile":    {"fx": "CLP=X", "equity": None, ...},
}

# Export commodities that generate the region's dollars.
COMMODITIES = {
    "Brent crude":  {"ticker": "BZ=F", "unit": "$/bbl"},
    "WTI crude":    {"ticker": "CL=F", "unit": "$/bbl"},
    "Copper":       {"ticker": "HG=F", "unit": "$/lb"},
    "Soybeans":     {"ticker": "ZS=F", "unit": "c/bu"},
}
# Basket = the three distinct export-dollar streams (oil, copper, soy), equal weighted.
BASKET_COMPONENTS = {"Oil (Brent)": "BZ=F", "Copper": "HG=F", "Soybeans": "ZS=F"}

COUNTRY_PALETTE = ["#1f6feb", "#d29922", "#2da44e", "#cf222e"]
COMMODITY_PALETTE = ["#3d5a80", "#98c1d9", "#b06d3b", "#6a7f3f"]

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}

# -----------------------------------------------------------------------------
# Data fetchers (cached so the app does not hammer the APIs)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yf_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Pull daily close history for a yfinance ticker. Empty df on failure."""
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
    """Pull a Banco Central do Brasil SGS series (no API key needed)."""
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


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
PERIOD_DAYS = {"1M": 30, "3M": 90, "6M": 180, "1Y": 366}


def slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Filter a dated dataframe to the selected lookback window."""
    if df.empty:
        return df
    end = df.index.max()
    if period == "YTD":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    else:
        start = end - pd.Timedelta(days=PERIOD_DAYS.get(period, 366))
    return df[df.index >= start]


def latest_and_change(df: pd.DataFrame, col: str):
    """Latest level, 1-day change, and change over the sliced window."""
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


def line_chart(df, title, names=None, normalize=False, yaxis_title=None, hover_dec=2):
    """Interactive line chart. Hover shows exact values; double-click a legend
    entry to isolate a single series."""
    plot_df = index_to_100(df) if normalize else df
    fig = go.Figure()
    for i, col in enumerate(plot_df.columns):
        s = plot_df[col].dropna()
        if s.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=s.index, y=s.values, mode="lines",
                name=(names or {}).get(col, col),
                line=dict(width=2, color=COUNTRY_PALETTE[i % len(COUNTRY_PALETTE)]),
                hovertemplate="%{y:." + str(hover_dec) + "f}<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        height=380, margin=dict(l=10, r=10, t=44, b=10),
        legend=dict(orientation="h", y=-0.16), hovermode="x unified",
        template="plotly_white", font=dict(family="Inter, Arial, sans-serif"),
    )
    fig.update_yaxes(title=yaxis_title or ("Indexed to 100 at window start" if normalize else None))
    return fig


def palette_for(fig, palette):
    for i, tr in enumerate(fig.data):
        tr.line.color = palette[i % len(palette)]
    return fig


# -----------------------------------------------------------------------------
# Header + global controls
# -----------------------------------------------------------------------------
st.title("LatAm Macro Monitor")

# Pull FX once to anchor the "as of" date and the headline section.
fx_raw = {c: fetch_yf_history(m["fx"]) for c, m in COUNTRIES.items()}
as_of = max(
    [df.index.max() for df in fx_raw.values() if not df.empty],
    default=None,
)
as_of_str = f"{as_of:%b %d, %Y}" if as_of is not None else "unavailable"
st.caption(f"Currencies, commodities, rates, and sovereign risk across the region  ·  Data as of {as_of_str}")

period = st.radio(
    "Lookback window",
    options=["1M", "3M", "6M", "YTD", "1Y"],
    index=4,  # default to 1Y so indexed values match published commentary
    horizontal=True,
)

st.markdown("---")

# -----------------------------------------------------------------------------
# Section 1: Currencies vs USD
# -----------------------------------------------------------------------------
st.subheader("Currencies vs. USD")
st.markdown(
    "<div class='section-note'>Quoted as USD per local currency, so a rising line means a weaker local currency.</div>",
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
                f"{meta['flag']} {country} (USD/{meta['code']})",
                f"{latest:,.2f}",
                f"{daily:+.2f}% d/d" if daily is not None else "n/a",
                delta_color="inverse",
            )
        else:
            st.metric(f"{meta['flag']} {country}", "n/a", "data unavailable")

fx_combined = pd.concat([df for df in fx_sliced.values() if not df.empty], axis=1).sort_index()
if not fx_combined.empty:
    names = {meta["fx"]: f"{meta['flag']} {c}" for c, meta in COUNTRIES.items()}
    fig = line_chart(fx_combined, f"Currency performance, {period} (indexed, higher = weaker local FX)",
                     names=names, normalize=True)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("FX history is temporarily unavailable. Yahoo Finance may be rate-limiting; refresh shortly.")

st.markdown("---")

# -----------------------------------------------------------------------------
# Section 2: Export commodities (the commodity-dollar channel)
# -----------------------------------------------------------------------------
st.subheader("Export Commodities")
st.markdown(
    "<div class='section-note'>The dollars behind the region. Oil, copper, and soy are the main export earners; "
    "rising prices feed dollar inflows.</div>",
    unsafe_allow_html=True,
)

cmdty_raw = {name: fetch_yf_history(m["ticker"]) for name, m in COMMODITIES.items()}
cmdty_cols = st.columns(len(COMMODITIES))
for (name, meta), col in zip(COMMODITIES.items(), cmdty_cols):
    sl = slice_period(cmdty_raw[name], period)
    latest, _, window = latest_and_change(sl, meta["ticker"])
    with col:
        if latest is not None:
            st.metric(
                f"{name} ({meta['unit']})",
                f"{latest:,.2f}",
                f"{window:+.1f}% {period}" if window is not None else "n/a",
            )
        else:
            st.metric(name, "n/a", "data unavailable")

cmdty_sliced = {n: slice_period(cmdty_raw[n], period) for n in COMMODITIES}
cmdty_combined = pd.concat([df for df in cmdty_sliced.values() if not df.empty], axis=1).sort_index()
if not cmdty_combined.empty:
    names = {meta["ticker"]: n for n, meta in COMMODITIES.items()}
    fig = line_chart(cmdty_combined, f"Commodity performance, {period} (indexed to 100 at window start)",
                     names=names, normalize=True)
    fig = palette_for(fig, COMMODITY_PALETTE)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

# LatAm export basket: equal-weighted index of oil, copper, soy
basket_parts = []
for label, ticker in BASKET_COMPONENTS.items():
    sl = slice_period(fetch_yf_history(ticker), period)
    if not sl.empty:
        s = sl[ticker].dropna()
        if not s.empty:
            basket_parts.append((s / s.iloc[0] * 100).rename(label))
if basket_parts:
    basket = pd.concat(basket_parts, axis=1).sort_index()
    basket["LatAm export basket"] = basket.mean(axis=1)
    bfig = go.Figure()
    bfig.add_trace(go.Scatter(
        x=basket.index, y=basket["LatAm export basket"], mode="lines",
        name="Export basket", line=dict(width=2.5, color="#b06d3b"),
        hovertemplate="%{y:.2f}<extra>Export basket</extra>",
    ))
    bfig.update_layout(
        title=dict(text=f"LatAm export-commodity basket, {period} (equal-weighted oil, copper, soy)", font=dict(size=15)),
        height=320, margin=dict(l=10, r=10, t=44, b=10), template="plotly_white",
        hovermode="x unified", font=dict(family="Inter, Arial, sans-serif"),
    )
    bfig.update_yaxes(title="Indexed to 100 at window start")
    st.plotly_chart(bfig, use_container_width=True, config=PLOTLY_CONFIG)

st.markdown("---")

# -----------------------------------------------------------------------------
# Section 3: Brazil rates and inflation (live from BCB)
# -----------------------------------------------------------------------------
st.subheader("Brazil 🇧🇷 · Policy Rate & Inflation")
st.markdown(
    "<div class='section-note'>Live from Banco Central do Brasil. Other countries can be added with a free FRED key.</div>",
    unsafe_allow_html=True,
)

c1, c2 = st.columns(2)
selic = fetch_bcb_series(432)
ipca12 = fetch_bcb_series(13522)

with c1:
    if not selic.empty:
        st.metric("Selic target (policy rate)", f"{selic['valor'].iloc[-1]:.2f}%")
        fig = go.Figure(go.Scatter(x=selic.index, y=selic["valor"], mode="lines",
                                   line=dict(width=2, color=COUNTRY_PALETTE[0]),
                                   hovertemplate="%{y:.2f}%<extra>Selic</extra>"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_white", yaxis_title="% p.a.")
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    else:
        st.info("Selic series unavailable right now.")

with c2:
    if not ipca12.empty:
        st.metric("IPCA inflation (12m)", f"{ipca12['valor'].iloc[-1]:.2f}%")
        fig = go.Figure(go.Scatter(x=ipca12.index, y=ipca12["valor"], mode="lines",
                                   line=dict(width=2, color=COUNTRY_PALETTE[1]),
                                   hovertemplate="%{y:.2f}%<extra>IPCA 12m</extra>"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_white", yaxis_title="% (12m accum.)")
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    else:
        st.info("IPCA series unavailable right now.")

st.markdown("---")

# -----------------------------------------------------------------------------
# Section 4: EM sovereign risk proxy
# -----------------------------------------------------------------------------
st.subheader("EM Sovereign Risk Proxy")
st.markdown(
    "<div class='section-note'>EMB = USD-denominated EM sovereign bonds, EMLC = local-currency. "
    "Falling prices imply wider spreads and rising risk premia. Broad EM, not Brazil-specific.</div>",
    unsafe_allow_html=True,
)
risk_raw = {t: fetch_yf_history(t) for t in ["EMB", "EMLC"]}
risk_sliced = pd.concat([slice_period(risk_raw[t], period) for t in risk_raw if not risk_raw[t].empty],
                        axis=1).sort_index()
if not risk_sliced.empty:
    fig = line_chart(risk_sliced, f"EM sovereign bond ETFs, {period} (indexed)",
                     names={"EMB": "EMB (USD)", "EMLC": "EMLC (local)"}, normalize=True)
    fig = palette_for(fig, ["#3d5a80", "#6a7f3f"])
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("ETF history temporarily unavailable.")

st.markdown("---")

# -----------------------------------------------------------------------------
# Section 5: Local equity indices
# -----------------------------------------------------------------------------
st.subheader("Local Equity Indices")
eq_raw = {c: fetch_yf_history(m["equity"]) for c, m in COUNTRIES.items() if m["equity"]}
eq_sliced = pd.concat([slice_period(eq_raw[c], period) for c in eq_raw if not eq_raw[c].empty],
                      axis=1).sort_index()
if not eq_sliced.empty:
    names = {meta["equity"]: f"{meta['flag']} {c}" for c, meta in COUNTRIES.items() if meta["equity"]}
    fig = line_chart(eq_sliced, f"Equity performance, {period} (indexed)", names=names, normalize=True)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("Equity history temporarily unavailable.")

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    <div class="source-note">
    <b>Sources:</b> Yahoo Finance (FX, commodities, ETFs, equity indices), Banco Central do Brasil SGS API
    (Selic, IPCA).<br>
    <b>Methodology:</b> FX quoted as USD per local currency, so a rising line is a weaker local currency.
    Performance charts indexed to 100 at the start of the selected window. The export basket is an equal-weighted
    index of Brent crude, copper, and soybeans, a simple proxy for the region's export-dollar earnings, to be
    refined with trade-weighted shares. Sovereign risk proxied via EM bond ETFs given no free real-time EMBI feed.<br>
    Data delayed and for research and educational purposes only. Not investment advice.
    </div>
    """,
    unsafe_allow_html=True,
)
