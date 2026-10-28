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
| Credit growth vs. income | Bank loan growth (`TOTLL`), loan growth minus nominal GDP growth (`TOTLL` vs `GDP`), private debt/GDP (`QUSPAM770A`) | Weekly / quarterly |
| Delinquencies | Credit card (`DRCCLACBS`), all loans (`DRALACBS`), commercial real estate (`DRCRELEXFACBS`) | Quarterly |
| Spending, income & jobs | Sahm rule (`SAHMREALTIME`), payrolls (`PAYEMS`), real disposable income (`DSPIC96`), real spending (`PCEC96`), yield curve (`T10Y3M`) | Daily / monthly |

**Scoring:** each indicator is green, yellow or red against thresholds in `scripts/indicators.py`. Each area takes the
average of its indicators. The overall verdict is:

- **All clear:** no red areas and fewer than 3 yellow
- **Watch:** 1 red area, or 3 or more yellow
- **Warning:** 2–3 red areas at once
- **High risk:** 4 or more red areas at once

## Value checklist page

`docs/companies.html` scores companies the way Buffett and Munger judge a business, using up to 10 years of
annual results from SEC filings:

- **10 business checks:** consistent profits, return on equity ≥ 15%, gross margin ≥ 40%, net margin ≥ 10%,
  positive free cash flow, earnings backed by cash, long-term debt ≤ 4 years of earnings, capex ≤ 50% of earnings,
  EPS growth ≥ 5% a year and share dilution ≤ 1% a year
- **Intrinsic value:** 10-year discounted owner earnings, then a 25% margin of safety gives the **buy-below price**.
  Owner earnings = the median free-cash-flow margin of the last 5 years × the latest revenue. Growth = the average of
  past revenue and EPS growth (0–15%), then 3% a year after year 10. The discount rate is the 10-year Treasury yield
  plus 4% (minimum 8%).
- **Price assumes:** the same math run backwards, giving the yearly growth today's price needs. Compare it with the
  company's past growth.
- **Verdicts:** Buy candidate, Wait for a better price, Doesn't fit, or Too early (fewer than 3 years of results)

It covers two lists:
- **Watchlist:** the tickers in `watchlist.txt`. Add or remove them from the page itself: open
  "Add or remove companies from this page" on the Watchlist tab and connect a fine-grained GitHub token
  (this repository only; Contents and Actions read & write). The page commits the change and starts a quick
  watchlist-only rescore (a few minutes). The token is stored only in that browser. You can also edit the file on GitHub.
- **Recent IPOs:** found automatically from SEC IPO prospectus filings (form 424B4) in the last 12 months,
  excluding SPACs and funds. Most show "Too early", which matches Buffett's own caution about IPOs.

- **Discover:** every day the update scans 250 more of the ~6,000 NYSE/Nasdaq companies (each is rescanned
  monthly). Those with a market value of $100M–$10B, revenue growing 10%+ a year and passing the business checks
  join a pool. Each time you open the page it shows 25 random picks from that pool, and a Shuffle button draws more.
  The pool fills up over the first 3–4 weeks.

- **My holdings:** enter your positions (ticker, shares, price paid, optional date). Each one gets a
  Buffett/Munger hold-or-sell stance from the checklist data (Buy-more zone, Hold, Hold don't add, Consider trimming,
  Review your thesis), with notes on valuation, position size, US tax treatment of each lot and current alternatives.
  **Holdings are stored only in your browser and never written to this public repository**; use Export/Import to move
  them between devices. Unscored tickers can be added to the watchlist (only the ticker becomes public).

**BUY / SELL alert:** when you open either page, a banner lists **BUY** (green) for any company marked a buy
candidate (passes the business checks and trades below its buy-below price) and **SELL** (red) for any of your holdings
whose business no longer passes the checklist, or that trades above twice its estimated value at 40+ times earnings.
Each item links to the company. "Dismiss" hides it until the set of signals changes.

All thresholds are in `scripts/value_rules.py`. Optionally add a repository secret `SEC_USER_AGENT` set to
`Your Name your@email`, which the SEC asks automated tools to send.

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
- `scripts/value_rules.py`, `scripts/fetch_companies.py`, `watchlist.txt`: the value checklist page
- `docs/`: the web pages (`index.html`, `companies.html` and their scripts, `style.css`)
- `.github/workflows/update-data.yml`: the daily automatic update

*Educational tool, not investment advice. This product uses the FRED® API but is not endorsed or certified by the
Federal Reserve Bank of St. Louis.*
