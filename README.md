# LatAm-Macro-Monitor

Live dashboard tracking FX, rates, inflation, and sovereign risk across Brazil, Mexico, Colombia, and Chile. The live version: https://latam-macro-monitor.streamlit.app. It's what I link from my market commentary and drop on applications.

Everything runs on free data. FX, the bond ETFs, and the equity indices come from Yahoo Finance. Brazil's Selic rate and IPCA inflation pull from the central bank's SGS API, which is open and needs no key. The other three countries' rates and inflation are next on my list once I wire in FRED.

To deploy your own, put the three files in a public GitHub repo and deploy through share.streamlit.io. It signs in with GitHub and gives you a live URL in about two minutes. To run it locally instead: pip install -r requirements.txt then streamlit run app.py.

Still working on it. I want to add the other countries' rate and inflation series, swap the ETF risk proxy for actual EMBI spreads once I have access, and build a panel that flags the biggest weekly moves so it feeds straight into what I write. A daily refresh on GitHub Actions is on there too so the numbers don't go stale.

Data is delayed and this is for research, not investment advice.
