"""Buffett/Munger-style business checks, intrinsic value and verdicts.

Pure functions only (no network) so they can be unit tested. Thresholds live in RULES;
edit them there to make the screen stricter or looser.
"""

from datetime import date, timedelta

RULES = {
    "min_years": 3,               # fewer annual reports than this -> "too early to judge"
    "profit_years": 5,            # years of unbroken profits needed to pass consistency
    "min_roe": 15.0,              # average return on equity, %
    "min_gross_margin": 40.0,     # average gross margin, % (pricing-power / moat signal)
    "min_net_margin": 10.0,       # average net margin, %
    "min_cash_conversion": 80.0,  # free cash flow as % of net income
    "max_debt_years": 4.0,        # long-term debt payable from this many years of earnings
    "max_capex_share": 50.0,      # capex as % of net income
    "min_growth": 5.0,            # per-share earnings growth, % a year
    "max_dilution": 1.0,          # share count growth, % a year
    "discount_rate": 0.10,        # required annual return for intrinsic value
    "terminal_growth": 0.03,      # growth after year 10
    "max_growth": 0.12,           # cap on the growth assumed for years 1-10
    "margin_of_safety": 0.25,     # buy-below discount to intrinsic value
    "pass_share": 0.70,           # share of quality checks that must pass
    "lockup_days": 180,           # typical IPO insider lock-up
    # "Hidden gem" screen for the Discover tab
    "gem_min_cap": 100e6,         # market value at least $100M
    "gem_max_cap": 10e9,          # ...and at most $10B (under the radar)
    "gem_min_revenue_growth": 10.0,  # revenue growth, % a year
}

PASS, FAIL, NA = "pass", "fail", "na"


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _cagr(first, last, years):
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _ratio(a, b):
    return a / b * 100 if a is not None and b not in (None, 0) else None


def check(key, title, status, value, target, explain):
    return {"key": key, "title": title, "status": status,
            "value": None if value is None else round(value, 2), "target": target, "explain": explain}


def threshold(value, minimum=None, maximum=None):
    if value is None:
        return NA
    if minimum is not None:
        return PASS if value >= minimum else FAIL
    return PASS if value <= maximum else FAIL


def quality_checks(years, r=RULES):
    """`years` is a list of annual dicts sorted oldest -> newest (see fetch_companies.annual_table)."""
    last10 = years[-10:]
    ni = [y.get("net_income") for y in last10]
    rev = [y.get("revenue") for y in last10]
    fcf = [y.get("fcf") for y in last10]
    latest = years[-1]

    known_ni = [v for v in ni if v is not None]
    if any(v <= 0 for v in known_ni):
        profit_status = FAIL
    elif len(known_ni) >= r["profit_years"]:
        profit_status = PASS
    else:
        profit_status = NA
    losses = sum(1 for v in known_ni if v <= 0)

    roe = _avg([_ratio(y.get("net_income"), y.get("equity")) if (y.get("equity") or 0) > 0 else None
                for y in last10])
    gross = _avg([_ratio(y.get("gross_profit"), y.get("revenue")) for y in last10])
    net = _avg([_ratio(n, v) for n, v in zip(ni, rev)])

    recent_fcf = [v for v in fcf[-5:] if v is not None]
    fcf_status = NA if not recent_fcf else (PASS if all(v > 0 for v in recent_fcf) else FAIL)
    conversion = _ratio(sum(v for v in fcf if v is not None),
                        sum(v for v, f in zip(ni, fcf) if v is not None and f is not None) or None)

    ni_latest = latest.get("net_income")
    debt = latest.get("debt")
    if debt is None:
        debt_years, debt_status = None, NA
    elif debt == 0:
        debt_years, debt_status = 0.0, PASS
    elif ni_latest and ni_latest > 0:
        debt_years = debt / ni_latest
        debt_status = threshold(debt_years, maximum=r["max_debt_years"])
    else:
        debt_years, debt_status = None, FAIL

    capex_share = _ratio(sum(y["capex"] for y in last10 if y.get("capex") is not None and y.get("net_income")),
                         sum(y["net_income"] for y in last10 if y.get("capex") is not None and y.get("net_income")))
    if capex_share is not None and capex_share < 0:
        capex_share = None  # cumulative losses make the ratio meaningless

    eps = [(y["end"], y["eps"]) for y in last10 if y.get("eps") is not None]
    growth = None
    if len(eps) >= 3:
        span = (date.fromisoformat(eps[-1][0]) - date.fromisoformat(eps[0][0])).days / 365.25
        growth = _cagr(eps[0][1], eps[-1][1], span)
    growth_status = threshold(growth, minimum=r["min_growth"])
    if growth is None and len(eps) >= 3:
        growth_status = FAIL  # earnings were negative at one end

    shares = [(y["end"], y["shares"]) for y in last10 if y.get("shares")]
    dilution = None
    if len(shares) >= 2:
        span = (date.fromisoformat(shares[-1][0]) - date.fromisoformat(shares[0][0])).days / 365.25
        dilution = _cagr(shares[0][1], shares[-1][1], span)

    return [
        check("profits", "Consistent profits", profit_status, losses,
              f"No losses over {r['profit_years']}+ years",
              f"{len(known_ni)} years of results, {losses} with a loss. Buffett wants a long, unbroken record of earnings."),
        check("roe", "High return on equity", threshold(roe, minimum=r["min_roe"]), roe,
              f"Average ≥ {r['min_roe']:g}%", "Profit earned on shareholders' money: a sign of a durable advantage."),
        check("gross_margin", "Pricing power (gross margin)", threshold(gross, minimum=r["min_gross_margin"]),
              gross, f"Average ≥ {r['min_gross_margin']:g}%",
              "High gross margins suggest a moat: customers pay up for the product."),
        check("net_margin", "Net profit margin", threshold(net, minimum=r["min_net_margin"]), net,
              f"Average ≥ {r['min_net_margin']:g}%", "How much of each sales dollar ends up as profit."),
        check("fcf", "Positive free cash flow", fcf_status,
              None if not recent_fcf else sum(1 for v in recent_fcf if v > 0),
              "Positive every year (last 5)", "Cash from operations after capital spending: Buffett's 'owner earnings'."),
        check("cash_conversion", "Earnings backed by cash", threshold(conversion, minimum=r["min_cash_conversion"]),
              conversion, f"Free cash flow ≥ {r['min_cash_conversion']:g}% of net income",
              "Reported profits should turn into real cash."),
        check("debt", "Conservative debt", debt_status, debt_years,
              f"Long-term debt ≤ {r['max_debt_years']:g} years of earnings",
              "Buffett favors companies that could pay off debt from a few years of profits."),
        check("capex", "Low capital needs", threshold(capex_share, maximum=r["max_capex_share"]), capex_share,
              f"Capital spending ≤ {r['max_capex_share']:g}% of net income",
              "Businesses that don't need heavy reinvestment free up cash for owners."),
        check("growth", "Growing earnings per share", growth_status, growth,
              f"≥ {r['min_growth']:g}% a year", "Steady per-share earnings growth over the years available."),
        check("dilution", "No heavy share dilution", threshold(dilution, maximum=r["max_dilution"]), dilution,
              f"Share count growth ≤ {r['max_dilution']:g}% a year",
              "Issuing lots of new shares (often stock pay) shrinks each owner's slice."),
    ]


def growth_rate(years, key):
    """Compound annual growth (%) of `key` over the last 10 years, or None."""
    pts = [(y["end"], y[key]) for y in years[-10:] if y.get(key) is not None]
    if len(pts) < 3:
        return None
    span = (date.fromisoformat(pts[-1][0]) - date.fromisoformat(pts[0][0])).days / 365.25
    return _cagr(pts[0][1], pts[-1][1], span)


def intrinsic_value(years, r=RULES):
    """10-year discounted owner earnings (free cash flow) per share, plus a terminal value."""
    recent = [y["fcf"] for y in years[-3:] if y.get("fcf") is not None]
    shares = years[-1].get("shares")
    if not recent or not shares:
        return None
    owner_earnings = sum(recent) / len(recent)
    if owner_earnings <= 0:
        return None
    growth_rates = []
    for key in ("revenue", "eps"):
        if len([y for y in years[-10:] if y.get(key) is not None]) >= 3:
            g = growth_rate(years, key)
            growth_rates.append(0.0 if g is None else g / 100)
    g = max(0.0, min(min(growth_rates) if growth_rates else 0.0, r["max_growth"]))
    d, tg = r["discount_rate"], r["terminal_growth"]
    value, cash = 0.0, owner_earnings
    for t in range(1, 11):
        cash *= 1 + g
        value += cash / (1 + d) ** t
    value += cash * (1 + tg) / (d - tg) / (1 + d) ** 10
    return {"per_share": value / shares, "owner_earnings": owner_earnings, "growth_used": g * 100}


def evaluate(years, price, treasury_yield, ipo_date=None, today=None, r=RULES):
    """Score one company. Returns checks, valuation numbers and a verdict."""
    today = today or date.today()
    result = {"years_of_data": len(years), "checks": [], "valuation": {}, "notes": []}
    if ipo_date:
        lockup = date.fromisoformat(ipo_date) + timedelta(days=r["lockup_days"])
        result["lockup_end"] = lockup.isoformat()
        if lockup > today:
            result["notes"].append(f"Insider lock-up likely ends around {lockup:%b %d, %Y}; extra selling pressure is common then.")
        result["notes"].append("Buffett avoids IPOs: the seller picks the timing and the price, "
                               "so new issues are rarely bargains.")
    if not years:
        result.update(verdict="no_data", verdict_text="No usable financial data in SEC filings yet.")
        return result

    latest = years[-1]
    checks = quality_checks(years, r)
    result["checks"] = checks
    iv = intrinsic_value(years, r)
    shares = latest.get("shares")
    val = result["valuation"]
    if iv:
        val.update(intrinsic_value=round(iv["per_share"], 2),
                   buy_below=round(iv["per_share"] * (1 - r["margin_of_safety"]), 2),
                   growth_used=round(iv["growth_used"], 1))
    revenue_growth = growth_rate(years, "revenue")
    if revenue_growth is not None:
        val["revenue_growth"] = round(revenue_growth, 1)
    if price:
        val["price"] = price
        if shares:
            val["market_cap"] = round(price * shares)
        if latest.get("eps") and latest["eps"] > 0:
            val["pe"] = round(price / latest["eps"], 1)
        if iv and shares:
            val["owner_earnings_yield"] = round(iv["owner_earnings"] / shares / price * 100, 2)
    if treasury_yield is not None:
        val["treasury_yield"] = treasury_yield

    scored = [c for c in checks if c["status"] != NA]
    passed = sum(c["status"] == PASS for c in scored)
    result["passed"], result["scored"] = passed, len(scored)
    core_ok = all(c["status"] != FAIL for c in checks if c["key"] in ("profits", "debt"))
    quality_ok = scored and passed / len(scored) >= r["pass_share"] and core_ok

    if len(years) < r["min_years"]:
        result.update(verdict="too_early",
                      verdict_text=f"Only {len(years)} year(s) of annual results. Buffett waits for a long track record.")
    elif not quality_ok:
        result.update(verdict="avoid", verdict_text=f"Doesn't meet the bar: passes {passed} of {len(scored)} business checks.")
    elif not price or not val.get("buy_below"):
        result.update(verdict="watch", verdict_text="Quality business; price or value estimate unavailable.")
    elif price <= val["buy_below"] and (treasury_yield is None
                                        or val.get("owner_earnings_yield", 0) >= treasury_yield):
        result.update(verdict="buy", verdict_text="Wonderful business at a fair price: trades below the buy-below price.")
    else:
        gap = (price / val["buy_below"] - 1) * 100
        result.update(verdict="watch",
                      verdict_text=f"Quality business, but {gap:.0f}% above the buy-below price. Wait for a better price.")
    return result


def is_hidden_gem(result, r=RULES):
    """Smaller, fast-growing company that passes the business checks (any price)."""
    val = result.get("valuation", {})
    cap, growth = val.get("market_cap"), val.get("revenue_growth")
    return (result.get("verdict") in ("buy", "watch") and cap is not None and growth is not None
            and r["gem_min_cap"] <= cap <= r["gem_max_cap"] and growth >= r["gem_min_revenue_growth"])
