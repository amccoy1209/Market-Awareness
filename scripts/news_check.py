"""News check for BUY candidates: price trend, recent SEC 8-K filings and headlines.

A cheap stock that passes every business check may be cheap for a reason the annual numbers don't show yet
(a lawsuit, a restatement, a new competitor). This gathers what the market may know. Network access is passed in
(see fetch_companies.attach_news_checks) so the parsing here can be tested offline.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime

FILING_DAYS = 180    # look back this far for 8-K filings
HEADLINE_DAYS = 30   # and this far for headlines
MAX_HEADLINES = 6
BIG_DROP = 40.0      # % below the 52-week high that gets flagged red
DROP = 25.0          # ...and yellow

# 8-K items worth knowing about, with how worrying they are.
ITEMS_8K = {
    "1.03": ("red", "Bankruptcy or receivership"),
    "1.05": ("red", "Material cybersecurity incident"),
    "2.05": ("yellow", "Restructuring, layoffs or exit costs"),
    "2.06": ("red", "Material impairment (writing down assets)"),
    "3.01": ("red", "Delisting notice or failure to meet listing rules"),
    "4.01": ("yellow", "Change of auditor"),
    "4.02": ("red", "Earlier financial statements can no longer be relied on (restatement)"),
    "5.02": ("yellow", "Director or senior officer departure or appointment"),
    "1.01": ("info", "Major agreement signed"),
    "2.01": ("info", "Acquisition or sale of assets completed"),
    "2.02": ("info", "Quarterly or annual results"),
    "8.01": ("info", "Other company announcement"),
}

LEGAL_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|plc|holdings?|group|n\.?v|s\.?a|/[a-z]+/?)\.?$", re.I)


def price_trend(points, today):
    """% below the 52-week high and % change over ~6 months, from [(iso date, close), ...]."""
    year = [(d, c) for d, c in points if d >= (today - timedelta(days=365)).isoformat()]
    if len(year) < 2:
        return {}
    last = year[-1][1]
    high = max(c for _, c in year)
    half_year = next((c for d, c in year if d >= (today - timedelta(days=182)).isoformat()), None)
    trend = {"below_high": round((1 - last / high) * 100, 1), "high_52w": round(high, 2)}
    if half_year:
        trend["change_6m"] = round((last / half_year - 1) * 100, 1)
    return trend


def recent_8k(submissions, cik, today):
    """8-K filings from the last FILING_DAYS, newest first, with plain-language item descriptions."""
    recent = submissions.get("filings", {}).get("recent", {})
    cutoff = (today - timedelta(days=FILING_DAYS)).isoformat()
    out = []
    for form, filed, items, accession, doc in zip(recent.get("form", []), recent.get("filingDate", []),
                                                   recent.get("items", []), recent.get("accessionNumber", []),
                                                   recent.get("primaryDocument", [])):
        if form not in ("8-K", "8-K/A") or filed < cutoff:
            continue
        codes = [c.strip() for c in (items or "").split(",") if c.strip() in ITEMS_8K]
        if not codes:
            continue
        out.append({
            "date": filed,
            "items": [{"code": c, "level": ITEMS_8K[c][0], "text": ITEMS_8K[c][1]} for c in codes],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}",
        })
    return sorted(out, key=lambda f: f["date"], reverse=True)


def search_name(company_name):
    """'INTUIT INC.' -> 'Intuit' for a news search."""
    name = company_name or ""
    for _ in range(2):
        name = LEGAL_SUFFIX.sub("", name.strip())
    return name.title() if name.isupper() else name


def headlines_url(company_name):
    query = f'"{search_name(company_name)}" stock when:{HEADLINE_DAYS}d'
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def parse_headlines(rss_bytes):
    """Newest headlines from a Google News RSS feed: [{title, source, date, url}]."""
    items = []
    for item in ET.fromstring(rss_bytes).iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        if not title or not link.startswith(("https://", "http://")):
            continue
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            published = None
        items.append({"title": title, "source": source, "date": published, "url": link})
    items.sort(key=lambda h: h["date"] or "", reverse=True)
    return items[:MAX_HEADLINES]


def flags_for(trend, filings):
    """Warnings worth reading before acting on a BUY, most serious first."""
    flags = []
    below = trend.get("below_high")
    if below is not None and below >= DROP:
        flags.append({"level": "red" if below >= BIG_DROP else "yellow",
                      "text": f"Down {below:.0f}% from its 52-week high of ${trend['high_52w']:,.2f}. Find out why before buying."})
    seen = set()
    for f in filings:
        for item in f["items"]:
            if item["level"] in ("red", "yellow") and item["code"] not in seen:
                seen.add(item["code"])
                flags.append({"level": item["level"], "text": f"{item['text']} (SEC 8-K filed {f['date']})"})
    return sorted(flags, key=lambda f: f["level"] != "red")


def build(trend, filings, headlines, today):
    return {
        "checked": today.isoformat(),
        "trend": trend,
        "flags": flags_for(trend, filings),
        "filings": filings[:8],
        "headlines": headlines,
    }
