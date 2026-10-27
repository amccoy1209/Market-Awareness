# Market-Awareness
Economic signals checked.

A simple dashboard that automatically checks Federal Reserve and FRED data for the early warning signs of a
**deleveraging or market downturn**, and tells you whether things look **all clear**, worth **watching**, or
**flashing a warning**. Each verdict shows the data behind it and when the next release is due.

## What it watches

Based on Ray Dalio's debt-cycle framework, one red signal is treated as noise and a **cluster** as the warning.

| Area | Indicators (FRED series) | Updates |
|---|---|---|
| Credit availability | Banks tightening business loans (`DRTSCILM`), credit cards (`DRTSCLCC`) | Quarterly (Fed SLOOS) |
| Debt-service pressure | Household debt service ratio, 1-yr change (`TDSP`) | Quarterly |
| Credit spreads & conditions | High-yield spread (`BAMLH0A0HYM2`), investment-grade spread (`BAMLC0A0CM`), Chicago Fed NFCI (`NFCI`) | Daily / weekly |
| Credit growth vs. income | Bank loan growth (`TOTLL`), loan growth minus nominal GDP growth (`TOTLL` vs `GDP`), private debt/GDP (`CRDQUSAPABIS`) | Weekly / quarterly |
| Delinquencies | Credit card (`DRCCLACBS`), all loans (`DRALACBS`), commercial real estate (`DRCRELEXFACBS`) | Quarterly |
| Spending, income & jobs | Sahm rule (`SAHMREALTIME`), payrolls (`PAYEMS`), real disposable income (`DSPIC96`), real spending (`PCEC96`), yield curve (`T10Y3M`) | Daily / monthly |

**Scoring:** each indicator is green, yellow or red against thresholds in `scripts/indicators.py`. Each area takes the
average of its indicators. The overall verdict is:

- **All clear:** no red areas and fewer than 3 yellow
- **Watch:** 1 red area, or 3 or more yellow
- **Warning:** 2–3 red areas at once
- **High risk:** 4 or more red areas at once

## Setup (one time, about 5 minutes)

1. **Get a free FRED API key:** https://fred.stlouisfed.org/docs/api/api_key.html
2. **Add it to GitHub:** repo **Settings → Secrets and variables → Actions → New repository secret**.
   Name: `FRED_API_KEY`, value: your key.
3. **Turn on the website:** **Settings → Pages → Build and deployment → Deploy from a branch**, then choose
   branch `main` and folder `/docs`.
4. **Load data now:** **Actions → Update market data → Run workflow.** After that it runs automatically every day.

Your dashboard will be at `https://<your-username>.github.io/market-awareness/`.

## Run it on your computer

```bash
export FRED_API_KEY=your_key
python scripts/fetch_data.py          # writes docs/data.json
python -m http.server -d docs 8000    # open http://localhost:8000
python -m unittest discover -s tests  # run the tests
```

No packages are needed beyond Python 3.10+.

## Project layout

- `scripts/indicators.py`: the indicator list, thresholds and scoring rules (**edit this to tune signals**)
- `scripts/fetch_data.py`: downloads data and release dates from FRED and writes `docs/data.json`
- `docs/`: the web page (`index.html`, `app.js`, `style.css`)
- `.github/workflows/update-data.yml`: the daily automatic update

*Educational tool, not investment advice. This product uses the FRED® API but is not endorsed or certified by the
Federal Reserve Bank of St. Louis.*
