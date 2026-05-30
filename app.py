"""
LatAm Macro Monitor
A live dashboard tracking FX, rates, inflation, and sovereign risk across
Brazil, Mexico, Colombia, and Chile.

Data sources (all free, no Bloomberg):
  - yfinance:       FX, sovereign-bond ETFs, local equity indices
  - BCB SGS API:    Brazil Selic target and IPCA inflation (no key required)
  - (optional) FRED: add a free key to extend rates/inflation to other countries

Author: Kimberly Villalta
"""

import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go

# ----------------------------------------------------------------------------- 
# Page setup + light styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="LatAm Macro Monitor",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1200px;}
        h1, h2, h3 {font-family: 'Georgia', serif; letter-spacing: -0.5px;}
        .stMetric {background: rgba(140,140,140,0.06); padding: 0.6rem 0.8rem; border-radius: 8px;}
        .source-note {color: #888; font-size: 0.78rem; line-height: 1.5;}
    </style>
    """,
    unsafe_allow_html=True,
)

# Country -> market tickers (yfinance) and BCB series codes where available
COUNTRIES = {
    "Brazil":   {"fx": "BRL=X", "equity": "^BVSP", "flag": "🇧🇷"},
    "Mexico":   {"fx": "MXN=X", "equity": "^MXX",  "flag": "🇲🇽"},
    "Colombia": {"fx": "COP=X", "equity": None,    "flag": "🇨🇴"},
    "Chile":    {"fx": "CLP=X", "equity": None,    "flag": "🇨🇱"},
}

PALETTE = ["#1f6feb", "#d29922", "#2da44e", "#cf222e"]

# ----------------------------------------------------------------------------- 
# Data fetchers (cached so the app does not hammer the APIs)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yf_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Pull daily close history for a yfinance ticker. Returns empty df on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty:
            return pd.DataFrame()
        return df[["Close"]].rename(columns={"Close": ticker})
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bcb_series(code: int, years: int = 3) -> pd.DataFrame:
    """Pull a Banco Central do Brasil SGS series (no API key needed)."""
    end = datetime.today()
    start = end - timedelta(days=365 * years)
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


def pct_change_from_history(df: pd.DataFrame, col: str):
    """Latest level and 1-day / month-to-date percentage change."""
    if df.empty or col not in df.columns or len(df) < 2:
        return None, None, None
    series = df[col].dropna()
    if len(series) < 2:
        return None, None, None
    latest = series.iloc[-1]
    daily = (series.iloc[-1] / series.iloc[-2] - 1) * 100
    month_start = series[series.index >= (series.index[-1].replace(day=1))]
    mtd = (series.iloc[-1] / month_start.iloc[0] - 1) * 100 if len(month_start) else None
    return latest, daily, mtd


def line_chart(df: pd.DataFrame, title: str, names: dict = None, normalize: bool = False):
    fig = go.Figure()
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        y = (s / s.iloc[0] * 100) if normalize else s
        fig.add_trace(
            go.Scatter(
                x=y.index, y=y.values, mode="lines",
                name=(names or {}).get(col, col),
                line=dict(width=2, color=PALETTE[i % len(PALETTE)]),
            )
        )
    fig.update_layout(
        title=title, height=360, margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=-0.15), hovermode="x unified",
        template="plotly_white",
    )
    if normalize:
        fig.update_yaxes(title="Indexed to 100 at start")
    return fig


# ----------------------------------------------------------------------------- 
# Header
# -----------------------------------------------------------------------------
st.title("LatAm Macro Monitor")
st.caption(
    f"FX, rates, inflation, and sovereign risk across the region  ·  "
    f"Last refreshed {datetime.now():%b %d, %Y %H:%M} UTC"
)

st.markdown("---")

# ----------------------------------------------------------------------------- 
# Section 1: FX snapshot (the headline row)
# -----------------------------------------------------------------------------
st.subheader("Currencies vs. USD")

fx_cols = st.columns(len(COUNTRIES))
fx_frames = {}
for (country, meta), col in zip(COUNTRIES.items(), fx_cols):
    hist = fetch_yf_history(meta["fx"])
    fx_frames[country] = hist
    latest, daily, _ = pct_change_from_history(hist, meta["fx"])
    with col:
        if latest is not None:
            st.metric(
                f"{meta['flag']} {country}  (USD/{meta['fx'][:3]})",
                f"{latest:,.2f}",
                f"{daily:+.2f}% d/d",
                delta_color="inverse",  # weaker local FX (higher USD/x) is "bad"
            )
        else:
            st.metric(f"{meta['flag']} {country}", "n/a", "data unavailable")

# Combined normalized FX chart
fx_combined = pd.concat(
    [df for df in fx_frames.values() if not df.empty], axis=1
).sort_index()
if not fx_combined.empty:
    name_map = {meta["fx"]: f"{meta['flag']} {c}" for c, meta in COUNTRIES.items()}
    st.plotly_chart(
        line_chart(fx_combined, "1Y currency performance (indexed, higher = weaker local FX)",
                   names=name_map, normalize=True),
        use_container_width=True,
    )
else:
    st.info("FX history is temporarily unavailable. Yahoo Finance may be rate-limiting; "
            "refresh in a few minutes.")

st.markdown("---")

# ----------------------------------------------------------------------------- 
# Section 2: Brazil rates & inflation (live from BCB, no key)
# -----------------------------------------------------------------------------
st.subheader("Brazil  🇧🇷  ·  Policy Rate & Inflation")
st.caption("Live from Banco Central do Brasil (SGS). Other countries can be added with a free FRED key.")

c1, c2 = st.columns(2)

selic = fetch_bcb_series(432)          # 432 = Selic target set by Copom
ipca12 = fetch_bcb_series(13522)       # 13522 = IPCA, 12-month accumulated %

with c1:
    if not selic.empty:
        cur = selic["valor"].iloc[-1]
        st.metric("Selic target (policy rate)", f"{cur:.2f}%")
        fig = go.Figure(go.Scatter(x=selic.index, y=selic["valor"], mode="lines",
                                   line=dict(width=2, color=PALETTE[0])))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_white", yaxis_title="% p.a.")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Selic series unavailable right now.")

with c2:
    if not ipca12.empty:
        cur = ipca12["valor"].iloc[-1]
        st.metric("IPCA inflation (12m)", f"{cur:.2f}%")
        fig = go.Figure(go.Scatter(x=ipca12.index, y=ipca12["valor"], mode="lines",
                                   line=dict(width=2, color=PALETTE[1])))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_white", yaxis_title="% (12m accum.)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("IPCA series unavailable right now.")

st.markdown("---")

# ----------------------------------------------------------------------------- 
# Section 3: Sovereign risk proxy (EM bond ETFs)
# -----------------------------------------------------------------------------
st.subheader("EM Sovereign Risk Proxy")
st.caption("EMB = USD-denominated EM sovereign bonds  ·  EMLC = local-currency EM sovereign bonds. "
           "Falling prices imply widening spreads / rising risk premia.")

emb = fetch_yf_history("EMB")
emlc = fetch_yf_history("EMLC")
risk = pd.concat([d for d in [emb, emlc] if not d.empty], axis=1).sort_index()
if not risk.empty:
    st.plotly_chart(
        line_chart(risk, "1Y EM sovereign bond ETFs (indexed)",
                   names={"EMB": "EMB (USD)", "EMLC": "EMLC (local)"}, normalize=True),
        use_container_width=True,
    )
else:
    st.info("ETF history temporarily unavailable.")

st.markdown("---")

# ----------------------------------------------------------------------------- 
# Section 4: Local equity indices
# -----------------------------------------------------------------------------
st.subheader("Local Equity Indices")
eq_frames = {}
for country, meta in COUNTRIES.items():
    if meta["equity"]:
        eq_frames[country] = fetch_yf_history(meta["equity"])
eq_combined = pd.concat([d for d in eq_frames.values() if not d.empty], axis=1).sort_index()
if not eq_combined.empty:
    name_map = {meta["equity"]: f"{meta['flag']} {c}"
                for c, meta in COUNTRIES.items() if meta["equity"]}
    st.plotly_chart(
        line_chart(eq_combined, "1Y equity performance (indexed)",
                   names=name_map, normalize=True),
        use_container_width=True,
    )
else:
    st.info("Equity history temporarily unavailable.")

# ----------------------------------------------------------------------------- 
# Footer
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    <div class="source-note">
    <b>Sources:</b> Yahoo Finance (FX, ETFs, equity indices), Banco Central do Brasil SGS API
    (Selic, IPCA). Data is delayed and for research/educational purposes only; not investment advice.<br>
    <b>Methodology:</b> FX shown as USD per local currency, so a rising line means a weaker local
    currency. Performance charts indexed to 100 at the start of the window. Sovereign risk proxied
    via EM bond ETFs in the absence of free real-time EMBI spread data.
    </div>
    """,
    unsafe_allow_html=True,
)
