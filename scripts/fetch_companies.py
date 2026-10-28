"""Score watchlist companies and recent US IPOs with Buffett/Munger-style checks.

Writes docs/companies.json. Data sources (all free):
  - SEC EDGAR: company financials (XBRL "company facts") and IPO filings (424B4 prospectuses)
  - Yahoo Finance chart API for share prices, with Stooq as a fallback
  - FRED: 10-year Treasury yield (needs FRED_API_KEY, optional)

Usage:
    python scripts/fetch_companies.py
Set SEC_USER_AGENT to "Your Name your@email" (SEC asks every tool to identify itself).
"""

import csv
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from value_rules import RULES, evaluate

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "companies.json"
WATCHLIST = ROOT / "watchlist.txt"
# The SEC rejects requests without a contact email. Override with a SEC_USER_AGENT secret if you like.
SEC_UA = os.environ.get("SEC_USER_AGENT") or "Market-Awareness 298371312+amccoy1209@users.noreply.github.com"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
IPO_WINDOW_DAYS = 365
MAX_IPOS = 200
SKIP_SIC = {"6770", "6221", "6722", "6726"}  # blank-check SPACs, commodity trusts, funds
PERIODIC_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "S-1", "S-1/A", "F-1", "F-1/A"}

# Financial concepts, in order of preference. Later tags fill years the earlier ones lack.
DURATION = {
    "revenue": ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:SalesRevenueNet", "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
                "ifrs-full:Revenue"],
    "gross_profit": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "cost_of_revenue": ["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold", "ifrs-full:CostOfSales"],
    "net_income": ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss",
                   "ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss"],
    "ocf": ["us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "eps": ["us-gaap:EarningsPerShareDiluted", "us-gaap:EarningsPerShareBasicAndDiluted",
            "ifrs-full:DilutedEarningsLossPerShare"],
    "shares": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
               "ifrs-full:AdjustedWeightedAverageShares"],
}
INSTANT = {
    "equity": ["us-gaap:StockholdersEquity",
               "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],
    "debt": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligations",
             "us-gaap:LongTermDebt", "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings"],
}
UNITS = {"eps": "USD/shares", "shares": "shares"}


# --- HTTP ---------------------------------------------------------------------

_last_sec_call = 0.0


def get(url, ua=SEC_UA, sec=True):
    """GET with retries. SEC calls are throttled to stay under its 10 requests/second limit."""
    global _last_sec_call
    for attempt in range(4):
        if sec:
            wait = 0.15 - (time.monotonic() - _last_sec_call)
            if wait > 0:
                time.sleep(wait)
            _last_sec_call = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as err:
            if err.code == 404 or (err.code < 500 and err.code != 429) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** (attempt + 1))


def get_json(url, **kw):
    return json.loads(get(url, **kw))


# --- SEC financials -----------------------------------------------------------

def _facts_for(facts, tag, unit):
    taxonomy, name = tag.split(":")
    return facts.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {}).get(unit, [])


def _annual_durations(facts, tags, unit):
    """{period_end: value} for ~12-month periods, preferring the most recently filed figure."""
    out = {}
    for tag in tags:
        found = {}
        for f in _facts_for(facts, tag, unit):
            if "start" not in f or f.get("form") not in ANNUAL_FORMS:
                continue
            days = (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
            if 350 <= days <= 380 and (f["end"] not in found or f["filed"] > found[f["end"]][1]):
                found[f["end"]] = (f["val"], f["filed"])
        for end, (val, _) in found.items():
            out.setdefault(end, val)
    return out


def _instants(facts, tags, unit="USD"):
    out = {}
    for tag in tags:
        found = {}
        for f in _facts_for(facts, tag, unit):
            if "start" not in f and (f["end"] not in found or f["filed"] > found[f["end"]][1]):
                found[f["end"]] = (f["val"], f["filed"])
        for end, (val, _) in found.items():
            out.setdefault(end, val)
    return out


def annual_table(facts):
    """Turn SEC company facts into a list of fiscal years (oldest first)."""
    series = {k: _annual_durations(facts, tags, UNITS.get(k, "USD")) for k, tags in DURATION.items()}
    inst = {k: _instants(facts, tags) for k, tags in INSTANT.items()}
    ends = sorted(set(series["net_income"]) | set(series["revenue"]))
    years = []
    for end in ends:
        y = {"end": end}
        for k in DURATION:
            y[k] = series[k].get(end)
        for k in INSTANT:
            y[k] = inst[k].get(end)
        if y["gross_profit"] is None and y["revenue"] is not None and y["cost_of_revenue"] is not None:
            y["gross_profit"] = y["revenue"] - y["cost_of_revenue"]
        if y["ocf"] is not None:
            y["fcf"] = y["ocf"] - (y["capex"] or 0)
        else:
            y["fcf"] = None
        years.append(y)
    return years[-10:]


def ticker_map():
    data = get_json("https://www.sec.gov/files/company_tickers.json")
    return {row["ticker"].upper(): (row["cik_str"], row["title"]) for row in data.values()}


def company_facts(cik):
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")


# --- Prices -------------------------------------------------------------------

def yahoo_chart(ticker, rng="1y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    res = get_json(url, ua=BROWSER_UA, sec=False)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0].get("close") or []
    points = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), c)
              for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
    return res["meta"].get("regularMarketPrice"), points


def stooq_price(ticker):
    text = get(f"https://stooq.com/q/l/?s={ticker.lower()}.us&f=sd2t2ohlcv&h&e=csv", ua=BROWSER_UA, sec=False)
    row = next(csv.DictReader(io.StringIO(text.decode())))
    return float(row["Close"]) if row.get("Close") not in (None, "", "N/D") else None


def price_info(ticker, ipo_date=None):
    """Latest price, plus the first trading-day close for IPOs."""
    try:
        price, points = yahoo_chart(ticker, "2y" if ipo_date else "5d")
        first = next((c for d, c in points if d >= ipo_date), None) if ipo_date else None
        if price:
            return round(price, 2), first and round(first, 2), "Yahoo Finance"
    except Exception as err:
        print(f"   Yahoo price failed for {ticker}: {err}", file=sys.stderr)
    try:
        price = stooq_price(ticker)
        return (round(price, 2) if price else None), None, "Stooq"
    except Exception as err:
        print(f"   Stooq price failed for {ticker}: {err}", file=sys.stderr)
    return None, None, None


def treasury_10y():
    if not os.environ.get("FRED_API_KEY"):
        return None
    try:
        from fetch_data import fred
        obs = fred("series/observations", series_id="DGS10", sort_order="desc", limit=10)["observations"]
        return next(float(o["value"]) for o in obs if o["value"] != ".")
    except Exception as err:
        print(f"!! 10-year Treasury yield unavailable: {err}", file=sys.stderr)
        return None


# --- IPO discovery ------------------------------------------------------------

FORM_IDX_LINE = re.compile(r"^(424B4)\s+(.+?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})\s+\S+\s*$")


def quarters_between(start, end):
    y, q = start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        yield y, q
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)


def parse_form_index(text, start, end):
    """{cik: earliest 424B4 date} from an EDGAR full-index form.idx file."""
    found = {}
    for line in text.splitlines():
        m = FORM_IDX_LINE.match(line)
        if m and start.isoformat() <= m.group(4) <= end.isoformat():
            cik = int(m.group(3))
            found[cik] = min(found.get(cik, m.group(4)), m.group(4))
    return found


def ipo_from_submissions(sub, first_424b4):
    """Return (ticker, exchange) if this filer looks like a true operating-company IPO, else None."""
    if sub.get("filings", {}).get("files"):
        return None  # more than ~1000 filings: long-established filer
    if str(sub.get("sic") or "") in SKIP_SIC:
        return None
    listed = [(t, e) for t, e in zip(sub.get("tickers") or [], sub.get("exchanges") or [])
              if e and e.upper() in {"NYSE", "NASDAQ", "NYSE AMERICAN", "NYSE ARCA", "CBOE"}]
    if not listed:
        return None
    recent = sub["filings"]["recent"]
    forms = list(zip(recent["form"], recent["filingDate"]))
    if not any(f in ("S-1", "F-1", "S-1/A", "F-1/A") for f, _ in forms):
        return None
    if any(f in PERIODIC_FORMS and d < first_424b4 for f, d in forms):
        return None  # was already filing annual/quarterly reports: a follow-on offering, not an IPO
    first_ipo_date = min(d for f, d in forms if f == "424B4")
    if first_ipo_date < first_424b4:
        return None
    # Prefer the shortest ticker (common stock rather than warrants/units).
    return min(listed, key=lambda te: len(te[0]))


def recent_ipos(today):
    start = today - timedelta(days=IPO_WINDOW_DAYS)
    candidates = {}
    for y, q in quarters_between(start, today):
        try:
            text = get(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx").decode("latin-1")
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue  # quarter index not published yet
            raise
        for cik, d in parse_form_index(text, start, today).items():
            candidates[cik] = min(candidates.get(cik, d), d)
    print(f"Found {len(candidates)} companies with 424B4 prospectuses since {start}")
    ipos = []
    for cik, first in sorted(candidates.items(), key=lambda kv: kv[1], reverse=True):
        try:
            sub = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception as err:
            print(f"   submissions failed for CIK {cik}: {err}", file=sys.stderr)
            continue
        listing = ipo_from_submissions(sub, first)
        if listing:
            ipos.append({"cik": cik, "name": sub.get("name"), "ticker": listing[0], "exchange": listing[1],
                         "ipo_date": first, "industry": sub.get("sicDescription")})
            if len(ipos) >= MAX_IPOS:
                break
    print(f"Identified {len(ipos)} IPOs")
    return ipos


# --- Assemble -----------------------------------------------------------------

def read_watchlist():
    tickers = []
    for line in WATCHLIST.read_text().splitlines():
        t = line.split("#")[0].strip().upper()
        if t and t not in tickers:
            tickers.append(t)
    return tickers


def build_entry(kind, ticker, cik, name, treasury, today, ipo=None):
    facts = company_facts(cik)
    years = annual_table(facts)
    price, first_close, price_source = price_info(ticker, ipo and ipo["ipo_date"])
    result = evaluate(years, price, treasury, ipo_date=ipo and ipo["ipo_date"], today=today)
    entry = {"kind": kind, "ticker": ticker, "name": facts.get("entityName") or name, "cik": cik,
             "price": price, "price_source": price_source,
             "sec_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
             "history": [{"end": y["end"], "revenue": y["revenue"], "net_income": y["net_income"], "fcf": y["fcf"]}
                         for y in years[-10:]],
             **result}
    if ipo:
        entry.update(ipo_date=ipo["ipo_date"], exchange=ipo["exchange"], industry=ipo["industry"],
                     first_close=first_close)
        if first_close and price:
            entry["change_since_first_close"] = round((price / first_close - 1) * 100, 1)
    return entry


def main():
    today = date.today()
    treasury = treasury_10y()
    tickers = ticker_map()
    errors, watchlist, ipos = [], [], []

    for t in read_watchlist():
        if t not in tickers:
            errors.append({"ticker": t, "error": "Ticker not found in SEC company list"})
            continue
        cik, name = tickers[t]
        print(f"Watchlist {t}")
        try:
            watchlist.append(build_entry("watchlist", t, cik, name, treasury, today))
        except Exception as err:
            print(f"!! {t}: {err}", file=sys.stderr)
            errors.append({"ticker": t, "error": str(err)})

    try:
        found = recent_ipos(today)
    except Exception as err:
        print(f"!! IPO discovery failed: {err}", file=sys.stderr)
        errors.append({"ticker": "IPOs", "error": f"IPO discovery failed: {err}"})
        found = []
    for ipo in found:
        print(f"IPO {ipo['ticker']} ({ipo['ipo_date']})")
        try:
            ipos.append(build_entry("ipo", ipo["ticker"], ipo["cik"], ipo["name"], treasury, today, ipo))
        except urllib.error.HTTPError as err:
            if err.code == 404:  # no XBRL financials filed yet
                ipos.append({"kind": "ipo", "ticker": ipo["ticker"], "name": ipo["name"], "cik": ipo["cik"],
                             "ipo_date": ipo["ipo_date"], "exchange": ipo["exchange"],
                             "industry": ipo["industry"], "checks": [], "valuation": {}, "notes": [],
                             "sec_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ipo['cik']}",
                             "verdict": "no_data",
                             "verdict_text": "No structured financial data filed with the SEC yet."})
            else:
                errors.append({"ticker": ipo["ticker"], "error": str(err)})
        except Exception as err:
            print(f"!! {ipo['ticker']}: {err}", file=sys.stderr)
            errors.append({"ticker": ipo["ticker"], "error": str(err)})

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "treasury_yield": treasury,
        "rules": RULES,
        "watchlist": watchlist,
        "ipos": ipos,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(output, separators=(",", ":")))
    print(f"Wrote {OUTPUT}: {len(watchlist)} watchlist companies, {len(ipos)} IPOs, {len(errors)} errors")
    if not watchlist and not ipos:
        sys.exit("No companies could be scored; check network access and SEC_USER_AGENT.")


if __name__ == "__main__":
    main()
