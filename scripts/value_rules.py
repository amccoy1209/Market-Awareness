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
    "equity_risk_premium": 0.04,  # required return = 10-year Treasury yield + this premium...
    "min_discount_rate": 0.08,    # ...but never below this
    "default_discount_rate": 0.09,  # used when the Treasury yield is unavailable
    "terminal_growth": 0.03,      # growth after year 10
    "max_growth": 0.15,           # cap on the growth assumed for years 1-10
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


def discount_rate_for(treasury_yield, r=RULES):
    """Required return: the 10-year Treasury yield plus an equity premium, with a floor."""
    if treasury_yield is None:
        return r["default_discount_rate"]
    return max(r["min_discount_rate"], treasury_yield / 100 + r["equity_risk_premium"])


def present_value(owner_earnings, growth, discount_rate, r=RULES):
    """Value of owner earnings growing at `growth` for 10 years, then at the terminal rate forever."""
    d, tg = discount_rate, r["terminal_growth"]
    value, cash = 0.0, owner_earnings
    for t in range(1, 11):
        cash *= 1 + growth
        value += cash / (1 + d) ** t
    return value + cash * (1 + tg) / (d - tg) / (1 + d) ** 10


def owner_earnings(years):
    """Typical free cash flow margin of the last 5 years applied to the latest revenue.

    The median margin ignores up to two one-off years (a large tax payment, an unusual capex year), and applying it
    to the latest revenue keeps growing companies from being valued on stale, smaller cash flows. Falls back to the
    plain average of free cash flow when revenue isn't reported.
    """
    recent = years[-5:]
    margins = sorted(y["fcf"] / y["revenue"] for y in recent if y.get("fcf") is not None and y.get("revenue"))
    if margins and years[-1].get("revenue"):
        mid = len(margins) // 2
        median = margins[mid] if len(margins) % 2 else (margins[mid - 1] + margins[mid]) / 2
        return median * years[-1]["revenue"]
    fcf = [y["fcf"] for y in recent if y.get("fcf") is not None]
    return sum(fcf) / len(fcf) if fcf else None


def growth_estimate(years, r=RULES):
    """Average of past revenue and per-share earnings growth, between 0 and the cap (as a fraction)."""
    rates = []
    for key in ("revenue", "eps"):
        if len([y for y in years[-10:] if y.get(key) is not None]) >= 3:
            g = growth_rate(years, key)
            rates.append(0.0 if g is None else g / 100)  # None: a loss at one end, so assume no growth
    return max(0.0, min(sum(rates) / len(rates) if rates else 0.0, r["max_growth"]))


def intrinsic_value(years, discount_rate=None, r=RULES):
    """10-year discounted owner earnings per share, plus a terminal value."""
    shares = years[-1].get("shares")
    oe = owner_earnings(years)
    if not oe or oe <= 0 or not shares:
        return None
    d = r["default_discount_rate"] if discount_rate is None else discount_rate
    g = growth_estimate(years, r)
    return {"per_share": present_value(oe, g, d, r) / shares, "owner_earnings": oe,
            "growth_used": g * 100, "discount_rate": d * 100}


def implied_growth(price, owner_earnings_per_share, discount_rate, r=RULES):
    """Growth a year for 10 years that today's price assumes (reverse DCF), in %, or None if out of range."""
    if not price or not owner_earnings_per_share or owner_earnings_per_share <= 0:
        return None
    lo, hi = -0.20, 0.60
    if price < present_value(owner_earnings_per_share, lo, discount_rate, r) \
            or price > present_value(owner_earnings_per_share, hi, discount_rate, r):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if present_value(owner_earnings_per_share, mid, discount_rate, r) < price else (lo, mid)
    return (lo + hi) / 2 * 100


def evaluate(years, price, treasury_yield, ipo_date=None, today=None, r=RULES, per_share_ok=True):
    """Score one company. Returns checks, valuation numbers and a verdict.

    per_share_ok=False (foreign filers) skips per-share valuation: their US-listed ADRs often
    represent a different number of shares than the filing reports, so value per share can't be compared to price.
    """
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
    discount = discount_rate_for(treasury_yield, r)
    iv = intrinsic_value(years, discount, r) if per_share_ok else None
    shares = latest.get("shares") if per_share_ok else None
    if not per_share_ok:
        result["notes"].append("Foreign filer: US shares usually trade as ADRs representing a different number of "
                               "shares, so per-share value and P/E aren't shown. Business checks still apply.")
    val = result["valuation"]
    if iv:
        val.update(intrinsic_value=round(iv["per_share"], 2),
                   buy_below=round(iv["per_share"] * (1 - r["margin_of_safety"]), 2),
                   growth_used=round(iv["growth_used"], 1), discount_rate=round(iv["discount_rate"], 1))
    revenue_growth = growth_rate(years, "revenue")
    if revenue_growth is not None:
        val["revenue_growth"] = round(revenue_growth, 1)
    if price:
        val["price"] = price
        if shares:
            val["market_cap"] = round(price * shares)
        if per_share_ok and latest.get("eps") and latest["eps"] > 0:
            val["pe"] = round(price / latest["eps"], 1)
        if iv and shares:
            val["owner_earnings_yield"] = round(iv["owner_earnings"] / shares / price * 100, 2)
            implied = implied_growth(price, iv["owner_earnings"] / shares, discount, r)
            if implied is not None:
                val["implied_growth"] = round(implied, 1)
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
    # The discount rate already includes the Treasury yield, so bonds aren't compared a second time here.
    elif price <= val["buy_below"]:
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
