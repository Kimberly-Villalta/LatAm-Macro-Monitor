"""
LatAm Macro Monitor
A live dashboard tracking currencies, commodities, rates, inflation, and
sovereign risk across Brazil, Mexico, Colombia, and Chile.

Institutional-grade analyst dashboard design (Goldman Sachs precision standard).

Data sources (all free):
  - yfinance:    FX, commodities, sovereign-bond ETFs, local equity indices
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
        /* Institutional color palette */
        :root {
            --primary-dark: #1a1a1a;
            --secondary-gray: #6b7280;
            --accent-blue: #0052cc;
            --subtle-bg: #f9fafb;
            --border-light: #e5e7eb;
        }
        
        /* Core layout */
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 3.5rem;
            max-width: 1300px;
        }
        
        /* Typography: refined, institutional */
        h1 {
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 2.1rem;
            font-weight: 600;
            letter-spacing: -0.6px;
            color: var(--primary-dark);
            margin-bottom: 0.3rem;
        }
        
        h2 {
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 1.35rem;
            font-weight: 600;
            color: var(--primary-dark);
            margin-top: 1.8rem;
            margin-bottom: 0.6rem;
            letter-spacing: -0.4px;
        }
        
        /* Metrics: refined institutional cards */
        .stMetric {
            background: transparent;
            border: 1px solid var(--border-light);
            padding: 1.1rem 1.3rem;
            border-radius: 3px;
            box-shadow: none;
        }
        
        .stMetric > div:first-child {
            color: var(--secondary-gray);
            font-size: 0.8rem;
            font-weight: 500;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }
        
        .stMetric > div:nth-child(2) {
            color: var(--primary-dark);
            font-size: 1.65rem;
            font-weight: 600;
            font-family: 'Courier New', monospace;
            margin-top: 0.3rem;
        }
        
        /* Captions & notes */
        .stCaption {
            color: var(--secondary-gray);
            font-size: 0.8rem;
            font-weight: 400;
            letter-spacing: 0.3px;
        }
        
        .section-note {
            color: var(--secondary-gray);
            font-size: 0.875rem;
            margin-bottom: 1.2rem;
            font-weight: 400;
            line-height: 1.5;
        }
        
        .source-note {
            color: #9ca3af;
            font-size: 0.75rem;
            line-height: 1.7;
            font-weight: 400;
            margin-top: 1.5rem;
        }
        
        /* Subtle spacing instead of heavy dividers */
        hr {
            border: none;
            border-top: 1px solid var(--border-light);
            margin: 2.5rem 0;
            opacity: 0.6;
        }
        
        /* Radio buttons: clean */
        [role="radiogroup"] {
            gap: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# CONFIGURATION & METADATA
# ============================================================================
COUNTRIES = {
    "Brazil":   {"fx": "USDBRL=X", "equity": "^BVSP", "flag": "🇧🇷", "code": "BRL"},
    "Mexico":   {"fx": "MXN=X", "equity": "^MXX",  "flag": "🇲🇽", "code": "MXN"},
    "Colombia": {"fx": "COP=X", "equity": None,    "flag": "🇨🇴", "code": "COP"},
    "Chile":    {"fx": "CLP=X", "equity": None,    "flag": "🇨🇱", "code": "CLP"},
}

COMMODITIES = {
    "Brent crude":  {"ticker": "BZ=F", "unit": "$/bbl"},
    "WTI crude":    {"ticker": "CL=F", "unit": "$/bbl"},
    "Copper":       {"ticker": "HG=F", "unit": "$/lb"},
    "Soybeans":     {"ticker": "ZS=F", "unit": "c/bu"},
}

BASKET_COMPONENTS = {"Oil (Brent)": "BZ=F", "Copper": "HG=F", "Soybeans": "ZS=F"}

# Institutional color palette (muted, professional)
COLOR_PALETTE = {
    "primary_blue": "#0052cc",
    "secondary_orange": "#d97706",
    "tertiary_green": "#059669",
    "quaternary_red": "#dc2626",
    "neutral_gray": "#6b7280",
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}

# ============================================================================
# DATA FETCHERS (Cached)
# ============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yf_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch daily OHLC history from Yahoo Finance."""
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
    """Fetch Banco Central do Brasil SGS series (no API key required)."""
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

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
PERIOD_DAYS = {"1M": 30, "3M": 90, "6M": 180, "1Y": 366}

def slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Slice dataframe to selected lookback window."""
    if df.empty:
        return df
    end = df.index.max()
    if period == "YTD":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    else:
        start = end - pd.Timedelta(days=PERIOD_DAYS.get(period, 366))
    return df[df.index >= start]

def latest_and_change(df: pd.DataFrame, col: str):
    """Extract latest level, 1-day change, and window change."""
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
    """Rebase all series to 100 at window start."""
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        s = df[col].dropna()
        if not s.empty:
            out[col] = df[col] / s.iloc[0] * 100
    return out

# ============================================================================
# ADVANCED CHART FUNCTIONS
# ============================================================================
def dual_axis_line_chart(df1, df2, title, name1, name2, color1, color2):
    """Create dual-axis chart showing relationship between two series."""
    fig = go.Figure()
    
    # Left axis (primary)
    s1 = df1.iloc[:, 0].dropna() if isinstance(df1, pd.DataFrame) else df1.dropna()
    fig.add_trace(go.Scatter(
        x=s1.index, y=s1.values, mode="lines", name=name1,
        line=dict(width=2.5, color=color1),
        yaxis="y1",
        hovertemplate="%{y:.2f}<extra>" + name1 + "</extra>",
    ))
    
    # Right axis (secondary)
    s2 = df2.iloc[:, 0].dropna() if isinstance(df2, pd.DataFrame) else df2.dropna()
    fig.add_trace(go.Scatter(
        x=s2.index, y=s2.values, mode="lines", name=name2,
        line=dict(width=2.5, color=color2, dash="dash"),
        yaxis="y2",
        hovertemplate="%{y:.2f}<extra>" + name2 + "</extra>",
    ))
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, family="Georgia, serif")),
        height=380, margin=dict(l=50, r=50, t=50, b=10),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
        yaxis=dict(title=name1, position=0),
        yaxis2=dict(title=name2, overlaying="y", side="right"),
    )
    
    return fig

def area_chart(df, title, colors):
    """Create stacked area chart for cumulative view."""
    fig = go.Figure()
    
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=col,
            fill="tonexty" if i > 0 else "tozeroy",
            line=dict(width=0 if i > 0 else 2, color=colors[i % len(colors)]),
            stackgroup="one",
            hovertemplate="%{y:.2f}<extra>" + col + "</extra>",
        ))
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, family="Georgia, serif")),
        height=350, margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
    )
    
    return fig

def volatility_scatter(df, title, color):
    """Create scatter plot showing volatility and distribution."""
    s = df.iloc[:, 0].dropna() if isinstance(df, pd.DataFrame) else df.dropna()
    daily_returns = s.pct_change().dropna() * 100
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=s.index[1:], y=daily_returns.values,
        mode="markers",
        name="Daily return",
        marker=dict(size=4, color=color, opacity=0.6),
        hovertemplate="Date: %{x}<br>Daily return: %{y:.2f}%<extra></extra>",
    ))
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, family="Georgia, serif")),
        height=320, margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
        yaxis_title="Daily return (%)",
    )
    
    return fig

# ============================================================================
# HEADER & GLOBAL CONTROLS
# ============================================================================
st.title("LatAm Macro Monitor")

# Fetch FX data once to anchor timestamp
fx_raw = {c: fetch_yf_history(m["fx"]) for c, m in COUNTRIES.items()}
as_of = max([df.index.max() for df in fx_raw.values() if not df.empty], default=None)
as_of_str = f"{as_of:%b %d, %Y}" if as_of is not None else "unavailable"

st.caption(
    f"Institutional-grade monitoring of currencies, commodities, rates, and sovereign risk  ·  Data as of {as_of_str}"
)

period = st.radio(
    "Lookback window",
    options=["1M", "3M", "6M", "YTD", "1Y"],
    index=4,
    horizontal=True,
)

st.markdown("---")

# ============================================================================
# SECTION 1: CURRENCIES VS. USD (With Volatility Scatter)
# ============================================================================
st.markdown("## Currencies vs. USD")
st.markdown(
    "<div class='section-note'>Quoted as USD per local currency. A rising line signals currency weakness.</div>",
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
                f"{meta['flag']} {country}",
                f"{latest:,.2f}",
                f"{daily:+.2f}% d/d" if daily is not None else "—",
                delta_color="inverse",
            )
        else:
            st.metric(f"{meta['flag']} {country}", "—", "data unavailable")

# FX performance chart with indexed view
fx_combined = pd.concat([df for df in fx_sliced.values() if not df.empty], axis=1).sort_index()
if not fx_combined.empty:
    fx_indexed = index_to_100(fx_combined)
    names = {meta["fx"]: f"{meta['flag']} {c}" for c, meta in COUNTRIES.items()}
    
    fig = go.Figure()
    colors = [COLOR_PALETTE["primary_blue"], COLOR_PALETTE["secondary_orange"], 
              COLOR_PALETTE["tertiary_green"], COLOR_PALETTE["quaternary_red"]]
    
    for i, col in enumerate(fx_indexed.columns):
        s = fx_indexed[col].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=names.get(col, col),
            line=dict(width=2.5, color=colors[i % len(colors)]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    
    fig.update_layout(
        title=dict(text=f"FX Performance, {period} (indexed to 100)", font=dict(size=14, family="Georgia, serif")),
        height=380, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.12),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
    )
    
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("FX history temporarily unavailable.")

st.markdown("")

# ============================================================================
# SECTION 2: COMMODITIES & DUAL-AXIS: BRENT vs. BRL (Transmission Channel)
# ============================================================================
st.markdown("## Export Commodities & Currency Transmission")
st.markdown(
    "<div class='section-note'>Oil, copper, and soy generate dollar inflows. Dual-axis shows how commodity strength "
    "should strengthen local currency (but doesn't when capital drains dominate).</div>",
    unsafe_allow_html=True,
)

# Commodity metrics
cmdty_raw = {name: fetch_yf_history(m["ticker"]) for name, m in COMMODITIES.items()}
cmdty_cols = st.columns(len(COMMODITIES))
for (name, meta), col in zip(COMMODITIES.items(), cmdty_cols):
    sl = slice_period(cmdty_raw[name], period)
    latest, _, window = latest_and_change(sl, meta["ticker"])
    with col:
        if latest is not None:
            st.metric(
                f"{name}",
                f"{latest:,.2f}",
                f"{window:+.1f}% {period}" if window is not None else "—",
            )
        else:
            st.metric(name, "—", "unavailable")

# Dual-axis: Brent vs. BRL (showing the theoretical transmission channel)
brent_data = slice_period(cmdty_raw["Brent crude"], period)
brl_data = slice_period(fx_raw["Brazil"], period)

if not brent_data.empty and not brl_data.empty:
    brent_indexed = index_to_100(brent_data)
    brl_indexed = index_to_100(brl_data)
    
    fig_transmission = dual_axis_line_chart(
        brent_indexed, brl_indexed,
        title=f"Commodity Supply vs. Currency Strength, {period} (indexed)",
        name1="Brent Crude (supply channel)",
        name2="BRL/USD (what *should* happen)",
        color1=COLOR_PALETTE["secondary_orange"],
        color2=COLOR_PALETTE["primary_blue"],
    )
    
    st.plotly_chart(fig_transmission, use_container_width=True, config=PLOTLY_CONFIG)
    st.markdown(
        "<div class='section-note'><i>Divergence signals capital account drain overwhelming commodity support. "
        "When Brent rallies but BRL weakens, it confirms Scenario 2 (financing drain dominates).</i></div>",
        unsafe_allow_html=True,
    )

st.markdown("")

# Commodity basket as area chart
basket_parts = []
for label, ticker in BASKET_COMPONENTS.items():
    sl = slice_period(fetch_yf_history(ticker), period)
    if not sl.empty:
        s = sl[ticker].dropna()
        if not s.empty:
            basket_parts.append((s / s.iloc[0] * 100).rename(label))

if basket_parts:
    basket = pd.concat(basket_parts, axis=1).sort_index()
    
    fig_basket = go.Figure()
    basket_colors = [COLOR_PALETTE["secondary_orange"], COLOR_PALETTE["tertiary_green"], COLOR_PALETTE["neutral_gray"]]
    
    for i, col in enumerate(basket.columns):
        s = basket[col].dropna()
        fig_basket.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=col,
            line=dict(width=2, color=basket_colors[i]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    
    # Add composite basket
    basket_avg = basket.mean(axis=1)
    fig_basket.add_trace(go.Scatter(
        x=basket_avg.index, y=basket_avg.values, mode="lines", name="LatAm Export Basket",
        line=dict(width=3, color=COLOR_PALETTE["primary_blue"]),
        hovertemplate="%{y:.1f}<extra>LatAm Export Basket</extra>",
    ))
    
    fig_basket.update_layout(
        title=dict(text=f"LatAm Export-Commodity Basket, {period} (indexed, equal-weighted)",
                  font=dict(size=14, family="Georgia, serif")),
        height=340, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.12),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
    )
    
    st.plotly_chart(fig_basket, use_container_width=True, config=PLOTLY_CONFIG)

st.markdown("")

# ============================================================================
# SECTION 3: BRAZIL RATES & INFLATION (Institutional Layout)
# ============================================================================
st.markdown("## Brazil · Policy Rate & Inflation")
st.markdown(
    "<div class='section-note'>Selic at record-high levels signaling external constraint. Real rate ("
    "Selic − IPCA) is the relevant cost of capital for EM borrowers.</div>",
    unsafe_allow_html=True,
)

col1, col2 = st.columns(2)
selic = fetch_bcb_series(432)
ipca12 = fetch_bcb_series(13522)

with col1:
    if not selic.empty:
        latest_selic = selic["valor"].iloc[-1]
        st.metric("Selic Target Rate", f"{latest_selic:.2f}%", "Policy rate (p.a.)")
        
        # Selic chart with area fill
        fig_selic = go.Figure()
        fig_selic.add_trace(go.Scatter(
            x=selic.index, y=selic["valor"],
            mode="lines", name="Selic",
            fill="tozeroy",
            line=dict(width=2, color=COLOR_PALETTE["primary_blue"]),
            hovertemplate="%{y:.2f}%<extra>Selic</extra>",
        ))
        fig_selic.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_white", font=dict(family="system-ui, sans-serif", size=10),
            yaxis_title="% p.a."
        )
        st.plotly_chart(fig_selic, use_container_width=True, config=PLOTLY_CONFIG)
    else:
        st.info("Selic data unavailable.")

with col2:
    if not ipca12.empty:
        latest_ipca = ipca12["valor"].iloc[-1]
        st.metric("IPCA Inflation (12m)", f"{latest_ipca:.2f}%", "YoY inflation")
        
        # IPCA chart
        fig_ipca = go.Figure()
        fig_ipca.add_trace(go.Scatter(
            x=ipca12.index, y=ipca12["valor"],
            mode="lines", name="IPCA",
            fill="tozeroy",
            line=dict(width=2, color=COLOR_PALETTE["secondary_orange"]),
            hovertemplate="%{y:.2f}%<extra>IPCA 12m</extra>",
        ))
        fig_ipca.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_white", font=dict(family="system-ui, sans-serif", size=10),
            yaxis_title="% (12m accum.)"
        )
        st.plotly_chart(fig_ipca, use_container_width=True, config=PLOTLY_CONFIG)
    else:
        st.info("IPCA data unavailable.")

# Real rate: Selic - IPCA
if not selic.empty and not ipca12.empty:
    real_rate = selic.copy()
    real_rate["valor"] = selic["valor"] - ipca12["valor"]
    
    st.markdown("")
    st.markdown("### Real Rate (Selic − IPCA)")
    st.markdown(
        "<div class='section-note'>The true cost of capital for EM borrowers. Sticky high real rates trap policy.</div>",
        unsafe_allow_html=True,
    )
    
    fig_real = go.Figure()
    fig_real.add_trace(go.Scatter(
        x=real_rate.index, y=real_rate["valor"],
        mode="lines", name="Real rate",
        line=dict(width=2.5, color=COLOR_PALETTE["tertiary_green"]),
        hovertemplate="%{y:.2f}%<extra>Real rate</extra>",
    ))
    fig_real.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_real.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        template="plotly_white", font=dict(family="system-ui, sans-serif", size=10),
        yaxis_title="% p.a."
    )
    st.plotly_chart(fig_real, use_container_width=True, config=PLOTLY_CONFIG)

st.markdown("")

# ============================================================================
# SECTION 4: EM SOVEREIGN RISK PROXY (Dual-Axis: Spreads + Volatility)
# ============================================================================
st.markdown("## EM Sovereign Risk Proxy")
st.markdown(
    "<div class='section-note'>EMB (hard currency) vs. EMLC (local currency). Rising prices = lower spreads. "
    "Wide spreads + high VIX = capital flight regime.</div>",
    unsafe_allow_html=True,
)

risk_raw = {t: fetch_yf_history(t) for t in ["EMB", "EMLC"]}
risk_sliced = pd.concat(
    [slice_period(risk_raw[t], period) for t in risk_raw if not risk_raw[t].empty],
    axis=1,
).sort_index()

if not risk_sliced.empty:
    risk_indexed = index_to_100(risk_sliced)
    
    fig_risk = go.Figure()
    fig_risk.add_trace(go.Scatter(
        x=risk_indexed.index, y=risk_indexed["EMB"].dropna(),
        mode="lines", name="EMB (hard currency)",
        line=dict(width=2.5, color=COLOR_PALETTE["primary_blue"]),
        hovertemplate="%{y:.1f}<extra>EMB</extra>",
    ))
    fig_risk.add_trace(go.Scatter(
        x=risk_indexed.index, y=risk_indexed["EMLC"].dropna(),
        mode="lines", name="EMLC (local currency)",
        line=dict(width=2.5, color=COLOR_PALETTE["secondary_orange"], dash="dash"),
        hovertemplate="%{y:.1f}<extra>EMLC</extra>",
    ))
    
    fig_risk.update_layout(
        title=dict(text=f"EM Sovereign Bond ETFs, {period} (indexed)", font=dict(size=14, family="Georgia, serif")),
        height=360, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.12),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
    )
    
    st.plotly_chart(fig_risk, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("Sovereign risk data unavailable.")

st.markdown("")

# ============================================================================
# SECTION 5: LOCAL EQUITY INDICES (Volatility Scatter)
# ============================================================================
st.markdown("## Local Equity Indices")
st.markdown(
    "<div class='section-note'>Stock market resilience/weakness relative to macro stress. "
    "Wide volatility scatter signals uncertainty.</div>",
    unsafe_allow_html=True,
)

eq_raw = {c: fetch_yf_history(m["equity"]) for c, m in COUNTRIES.items() if m["equity"]}
eq_sliced = pd.concat(
    [slice_period(eq_raw[c], period) for c in eq_raw if not eq_raw[c].empty],
    axis=1,
).sort_index()

if not eq_sliced.empty:
    eq_indexed = index_to_100(eq_sliced)
    
    fig_eq = go.Figure()
    colors = [COLOR_PALETTE["primary_blue"], COLOR_PALETTE["secondary_orange"]]
    names = {meta["equity"]: f"{meta['flag']} {c}" for c, meta in COUNTRIES.items() if meta["equity"]}
    
    for i, col in enumerate(eq_indexed.columns):
        s = eq_indexed[col].dropna()
        if s.empty:
            continue
        fig_eq.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=names.get(col, col),
            line=dict(width=2.5, color=colors[i % len(colors)]),
            hovertemplate="%{y:.1f}<extra>%{fullData.name}</extra>",
        ))
    
    fig_eq.update_layout(
        title=dict(text=f"Equity Performance, {period} (indexed to 100)", font=dict(size=14, family="Georgia, serif")),
        height=360, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.12),
        hovermode="x unified",
        template="plotly_white",
        font=dict(family="system-ui, sans-serif", size=11),
    )
    
    st.plotly_chart(fig_eq, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("Equity history unavailable.")

st.markdown("")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.markdown(
    """
    <div class="source-note">
    <b>Sources:</b> Yahoo Finance (FX, commodities, ETFs, equity indices), Banco Central do Brasil SGS API (Selic, IPCA).<br>
    <b>Methodology:</b> FX quoted as USD per local currency. Indexed charts rebase to 100 at window start. 
    Export basket is equal-weighted (Brent, Copper, Soybeans). Real rate = Selic − IPCA. 
    Dual-axis charts show transmission mechanisms; divergence between commodity strength and FX weakness 
    signals capital account drain dominance.<br>
    <b>Disclaimer:</b> Data delayed, for research and educational purposes only. Not investment advice.
    </div>
    """,
    unsafe_allow_html=True,
)
