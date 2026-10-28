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
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from value_rules import RULES, discount_rate_for, evaluate, is_hidden_gem

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "companies.json"
WATCHLIST = ROOT / "watchlist.txt"
DISCOVERY_OUTPUT = ROOT / "docs" / "discovery.json"
DISCOVERY_PER_RUN = 250        # companies scanned per daily run, to stay gentle on the SEC
DISCOVERY_RESCAN_DAYS = 30     # how long before a company is scanned again
DISCOVERY_VERSION = 3          # bump when scoring logic changes, to rebuild the pool from scratch
PLAIN_TICKER = re.compile(r"^[A-Z]{1,5}$")  # skips warrants, units and preferred shares
# The SEC rejects requests without a contact email. Override with a SEC_USER_AGENT secret if you like.
# Collapse whitespace so a pasted secret with a stray line break still forms a valid header.
SEC_UA = " ".join(os.environ.get("SEC_USER_AGENT", "").split()) or "Market-Awareness 298371312+amccoy1209@users.noreply.github.com"
PRICE_UA = "Market-Awareness/1.0 (+https://github.com/amccoy1209/Market-Awareness)"
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
            "us-gaap:EarningsPerShareBasic", "ifrs-full:DilutedEarningsLossPerShare"],
    "shares": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
               "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", "ifrs-full:AdjustedWeightedAverageShares"],
}
INSTANT = {
    "equity": ["us-gaap:StockholdersEquity",
               "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],
    "debt": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligations",
             "us-gaap:LongTermDebt", "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings"],
}
UNITS = {"eps": "USD/shares", "shares": "shares"}
SPLIT_TOLERANCE = 0.12  # buybacks between filings blur the exact split ratio
SPLIT_RATIOS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50)


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
    years = years[-10:]
    repair_shares(years, _cover_shares(facts))
    adjust_for_splits(years)
    return years


def _cover_shares(facts):
    """{date: shares outstanding, summed across share classes} from filing cover pages."""
    by_filing = {}
    for f in _facts_for(facts, "dei:EntityCommonStockSharesOutstanding", "shares"):
        key = (f["end"], f.get("accn"))
        by_filing[key] = (by_filing.get(key, (0, ""))[0] + f["val"], f["filed"])
    best = {}
    for (end, _), (total, filed) in by_filing.items():
        if end not in best or filed > best[end][1]:
            best[end] = (total, filed)
    return {end: total for end, (total, _) in best.items()}


def repair_shares(years, cover):
    """Fix share counts that are missing (multi-class companies) or mis-scaled in the filing."""
    for y in years:
        ni, eps = y.get("net_income"), y.get("eps")
        implied = ni / eps if ni and eps and abs(eps) >= 0.05 else None
        if implied and implied > 0 and not (y.get("shares") and 0.5 <= y["shares"] / implied <= 2):
            y["shares"] = implied
        if not y.get("shares"):
            end = date.fromisoformat(y["end"])
            later = sorted(d for d in cover if end < date.fromisoformat(d) <= end + timedelta(days=150))
            if later:
                y["shares"] = cover[later[0]]
        if eps is None and y.get("shares") and ni is not None:
            y["eps"] = ni / y["shares"]


def adjust_for_splits(years):
    """Restate earlier years for stock splits, which old filings never restate."""
    for i in range(len(years) - 1, 0, -1):
        before, after = years[i - 1].get("shares"), years[i].get("shares")
        if not before or not after:
            continue
        ratio = after / before
        factor = next((r for r in SPLIT_RATIOS if abs(ratio / r - 1) < SPLIT_TOLERANCE), None)
        if factor is None:
            inverse = next((r for r in SPLIT_RATIOS if abs(ratio * r - 1) < SPLIT_TOLERANCE), None)
            factor = 1 / inverse if inverse else None  # reverse split
        if factor:
            for y in years[:i]:
                y["shares"] = y["shares"] * factor if y.get("shares") else y.get("shares")
                y["eps"] = y["eps"] / factor if y.get("eps") is not None else None


def foreign_filer(facts):
    """True if annual results come from 20-F/40-F reports (US shares are usually ADRs with their own ratio)."""
    return any(f.get("form", "").startswith(("20-F", "40-F"))
               for tag in DURATION["net_income"] + DURATION["revenue"] for f in _facts_for(facts, tag, "USD"))


def ticker_map():
    data = get_json("https://www.sec.gov/files/company_tickers.json")
    return {row["ticker"].upper(): (row["cik_str"], row["title"]) for row in data.values()}


def company_facts(cik):
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")


# --- Prices -------------------------------------------------------------------

def yahoo_chart(ticker, rng="1y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    res = get_json(url, ua=PRICE_UA, sec=False)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0].get("close") or []
    points = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), c)
              for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
    return res["meta"].get("regularMarketPrice"), points


def stooq_price(ticker):
    text = get(f"https://stooq.com/q/l/?s={ticker.lower()}.us&f=sd2t2ohlcv&h&e=csv", ua=PRICE_UA, sec=False)
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


# --- Discovery: rotating scan for under-the-radar companies ---------------------

def listed_universe(exclude):
    """{ticker: (cik, name)} for NYSE/Nasdaq companies, one plain ticker per company."""
    data = get_json("https://www.sec.gov/files/company_tickers_exchange.json")
    by_cik = {}
    for cik, name, ticker, exchange in data["data"]:
        t = (ticker or "").upper()
        if exchange not in ("NYSE", "Nasdaq") or not PLAIN_TICKER.match(t) or t in exclude:
            continue
        if cik not in by_cik or len(t) < len(by_cik[cik][0]):
            by_cik[cik] = (t, name)
    return {t: (cik, name) for cik, (t, name) in by_cik.items()}


def pick_batch(universe, scanned, today, n):
    """Never-scanned companies first (in random order), then the least recently scanned."""
    cutoff = (today - timedelta(days=DISCOVERY_RESCAN_DAYS)).isoformat()
    due = [t for t in universe if scanned.get(t, "") < cutoff]
    random.shuffle(due)
    due.sort(key=lambda t: scanned.get(t, ""))
    return due[:n]


def discover(treasury, today, exclude):
    try:
        previous = json.loads(DISCOVERY_OUTPUT.read_text())
    except (FileNotFoundError, ValueError):
        previous = {}
    if previous.get("version") != DISCOVERY_VERSION:
        previous = {}
    scanned = previous.get("scanned", {})
    gems = {g["ticker"]: g for g in previous.get("candidates", [])}
    universe = listed_universe(exclude)
    batch = pick_batch(universe, scanned, today, DISCOVERY_PER_RUN)
    print(f"Discovery: scanning {len(batch)} of {len(universe)} listed companies")
    failed = 0
    for t in batch:
        cik, name = universe[t]
        scanned[t] = today.isoformat()
        gems.pop(t, None)
        try:
            entry = build_entry("discovery", t, cik, name, treasury, today)
        except Exception:
            failed += 1  # usually no XBRL financials (funds, trusts, very new filers)
            continue
        if is_hidden_gem(entry):
            entry["scanned"] = today.isoformat()
            gems[t] = entry
    output = {
        "version": DISCOVERY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe": len(universe),
        "scanned_count": sum(1 for t in scanned if t in universe),
        "rules": RULES,
        "scanned": {t: d for t, d in scanned.items() if t in universe},
        "candidates": sorted((g for t, g in gems.items() if t in universe), key=lambda g: g["ticker"]),
    }
    DISCOVERY_OUTPUT.write_text(json.dumps(output, separators=(",", ":")))
    print(f"Discovery: {len(output['candidates'])} candidates in pool, "
          f"{output['scanned_count']}/{len(universe)} companies scanned so far, {failed} skipped this run")


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
    result = evaluate(years, price, treasury, ipo_date=ipo and ipo["ipo_date"], today=today,
                      per_share_ok=not foreign_filer(facts))
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


def score_ipos(treasury, today, errors):
    ipos = []
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
    return ipos


def main(watchlist_only=False):
    """Full daily run, or with watchlist_only just rescore watchlist.txt and keep the last IPO results."""
    today = date.today()
    treasury = treasury_10y()
    tickers = ticker_map()
    errors, watchlist = [], []

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

    if watchlist_only:
        try:
            previous = json.loads(OUTPUT.read_text())
        except (FileNotFoundError, ValueError):
            previous = {}
        ipos = previous.get("ipos", [])
        ipo_tickers = {i["ticker"] for i in ipos} | {"IPOs"}
        errors += [e for e in previous.get("errors", []) if e.get("ticker") in ipo_tickers]
    else:
        ipos = score_ipos(treasury, today, errors)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "treasury_yield": treasury,
        "discount_rate": round(discount_rate_for(treasury) * 100, 1),
        "rules": RULES,
        "watchlist": watchlist,
        "ipos": ipos,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(output, separators=(",", ":")))
    print(f"Wrote {OUTPUT}: {len(watchlist)} watchlist companies, {len(ipos)} IPOs, {len(errors)} errors")
    if not watchlist and not ipos:
        sys.exit("No companies could be scored; check network access and SEC_USER_AGENT.")
    if watchlist_only:
        return

    try:
        discover(treasury, today, exclude=set(read_watchlist()) | {i["ticker"] for i in ipos})
    except Exception as err:
        print(f"!! Discovery scan failed: {err}", file=sys.stderr)


if __name__ == "__main__":
    main(watchlist_only="--watchlist-only" in sys.argv)
