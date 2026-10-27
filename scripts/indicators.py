"""Indicator definitions and the rules that turn raw data into green/yellow/red signals.

Everything here is pure (no network), so it can be unit tested and tweaked safely.
To change a threshold, edit the `yellow` / `red` numbers in INDICATORS below.
"""

from dataclasses import dataclass
from datetime import timedelta

GREEN, YELLOW, RED = "green", "yellow", "red"
SCORES = {GREEN: 0, YELLOW: 1, RED: 2}

CATEGORIES = [
    ("credit_availability", "Credit availability", "Are banks making it harder to borrow?"),
    ("debt_service", "Debt-service pressure", "Are debt payments eating a bigger share of income?"),
    ("credit_spreads", "Credit spreads & financial conditions", "Are lenders demanding more to take risk?"),
    ("credit_growth", "Credit growth vs. income", "Is borrowing slowing relative to the economy?"),
    ("delinquencies", "Delinquencies", "Are borrowers falling behind on payments?"),
    ("real_economy", "Spending, income & jobs", "Is debt stress reaching the real economy?"),
]


@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    series: str              # FRED series ID used for the signal
    category: str
    metric: str              # how the signal value is computed (see compute_metric)
    unit: str
    yellow: float            # threshold for a yellow signal
    red: float               # threshold for a red signal
    higher_is_worse: bool
    stale_days: int          # flag data whose latest observation is older than this
    why: str
    compare_series: str | None = None  # second series for "yoy_gap"


INDICATORS = [
    # 1. Credit availability (Fed Senior Loan Officer Survey, quarterly)
    Indicator("sloos_ci", "Banks tightening business loan standards", "DRTSCILM",
              "credit_availability", "level", "% of banks (net)", 10, 30, True, 200,
              "Net share of banks tightening standards on loans to large and mid-size firms. "
              "Readings above ~30% have preceded most recessions."),
    Indicator("sloos_cards", "Banks tightening credit card standards", "DRTSCLCC",
              "credit_availability", "level", "% of banks (net)", 10, 25, True, 200,
              "Net share of banks tightening standards on credit cards: an early read on household credit access."),

    # 2. Debt-service pressure
    Indicator("household_dsr", "Household debt service ratio (1-yr change)", "TDSP",
              "debt_service", "change_1y", "pts of income", 0.2, 0.5, True, 270,
              "Required household debt payments as a share of disposable income. A sustained rise "
              "means debt is squeezing budgets."),

    # 3. Credit spreads & financial conditions (daily/weekly)
    Indicator("hy_spread", "High-yield bond spread", "BAMLH0A0HYM2",
              "credit_spreads", "level", "%", 4.5, 6.0, True, 10,
              "Extra yield investors demand to hold junk bonds over Treasuries. Sharp widening "
              "signals lenders pulling back from riskier borrowers."),
    Indicator("ig_spread", "Investment-grade bond spread", "BAMLC0A0CM",
              "credit_spreads", "level", "%", 1.3, 2.0, True, 10,
              "Extra yield on high-quality corporate bonds. Widening here means stress is spreading "
              "beyond the weakest borrowers."),
    Indicator("nfci", "Chicago Fed financial conditions", "NFCI",
              "credit_spreads", "level", "index", -0.25, 0.0, True, 21,
              "Broad measure of credit, risk and leverage conditions. Above 0 means tighter than average."),

    # 4. Credit growth vs. income
    Indicator("credit_growth", "Bank loan growth (1-yr)", "TOTLL",
              "credit_growth", "yoy_pct", "%", 2.0, 0.0, False, 21,
              "Year-over-year growth in total bank loans. Shrinking credit is a hallmark of deleveraging."),
    Indicator("credit_vs_gdp", "Bank loan growth minus nominal GDP growth", "TOTLL",
              "credit_growth", "yoy_gap", "pts", 0.0, -4.0, False, 200,
              "When credit grows slower than incomes, the economy is paying debt down relative to income.",
              compare_series="GDP"),
    Indicator("private_debt_gdp", "Private debt to GDP (1-yr change)", "CRDQUSAPABIS",
              "credit_growth", "change_1y", "pts of GDP", -0.5, -3.0, False, 400,
              "BIS measure of private non-financial debt relative to GDP. A falling ratio means "
              "deleveraging is underway (lags by a few quarters)."),

    # 5. Delinquencies (quarterly)
    Indicator("card_delinq", "Credit card delinquency rate (1-yr change)", "DRCCLACBS",
              "delinquencies", "change_1y", "pts", 0.2, 0.5, True, 200,
              "Change in the share of credit card balances 30+ days past due."),
    Indicator("all_loan_delinq", "All-loan delinquency rate (1-yr change)", "DRALACBS",
              "delinquencies", "change_1y", "pts", 0.1, 0.3, True, 200,
              "Change in the delinquency rate across all bank loans: shows whether stress is broadening."),
    Indicator("cre_delinq", "Commercial real estate delinquency (1-yr change)", "DRCRELEXFACBS",
              "delinquencies", "change_1y", "pts", 0.2, 0.5, True, 200,
              "Change in delinquencies on commercial real estate loans (excluding farmland)."),

    # 6. Spending, income & jobs
    Indicator("sahm", "Sahm rule recession indicator", "SAHMREALTIME",
              "real_economy", "level", "pts", 0.3, 0.5, True, 60,
              "Rise in the 3-month average unemployment rate vs. its prior-year low. 0.5+ has marked "
              "the start of every recession since 1970."),
    Indicator("payrolls", "Job growth (3-month average)", "PAYEMS",
              "real_economy", "avg_change_3", "thousand jobs/mo", 75, 0, False, 60,
              "Average monthly change in nonfarm payrolls over the last three months."),
    Indicator("real_income", "Real disposable income (1-yr)", "DSPIC96",
              "real_economy", "yoy_pct", "%", 1.5, 0.0, False, 75,
              "Inflation-adjusted after-tax income growth. Falling income makes debt harder to carry."),
    Indicator("real_spending", "Real consumer spending (1-yr)", "PCEC96",
              "real_economy", "yoy_pct", "%", 1.5, 0.0, False, 75,
              "Inflation-adjusted consumer spending growth. Cutbacks confirm debt stress is biting."),
    Indicator("yield_curve", "Yield curve (10-yr minus 3-month)", "T10Y3M",
              "real_economy", "level", "pts", 0.5, 0.0, False, 10,
              "Longer-lead recession warning: inversion (below 0) has preceded recessions, "
              "though with false alarms and long lags."),
]


# --- Metric calculations ------------------------------------------------------
# `obs` is a list of (date, float) sorted oldest -> newest.

def value_on_or_before(obs, target):
    """Latest observation on or before `target` date, or None."""
    found = None
    for d, v in obs:
        if d > target:
            break
        found = (d, v)
    return found


def change_1y(obs):
    latest_date, latest = obs[-1]
    prior = value_on_or_before(obs, latest_date - timedelta(days=365))
    return None if prior is None else latest - prior[1]


def yoy_pct(obs):
    latest_date, latest = obs[-1]
    prior = value_on_or_before(obs, latest_date - timedelta(days=365))
    if prior is None or prior[1] == 0:
        return None
    return (latest / prior[1] - 1) * 100


def avg_change(obs, n):
    if len(obs) < n + 1:
        return None
    window = [v for _, v in obs[-(n + 1):]]
    return (window[-1] - window[0]) / n


def yoy_gap(obs, compare_obs):
    """Credit YoY growth minus comparison YoY growth, aligned to the comparison's latest date."""
    compare_growth = yoy_pct(compare_obs)
    aligned = [o for o in obs if o[0] <= compare_obs[-1][0]]
    if compare_growth is None or not aligned:
        return None
    growth = yoy_pct(aligned)
    return None if growth is None else growth - compare_growth


def compute_metric(ind, obs, compare_obs=None):
    if not obs:
        return None
    if ind.metric == "level":
        return obs[-1][1]
    if ind.metric == "change_1y":
        return change_1y(obs)
    if ind.metric == "yoy_pct":
        return yoy_pct(obs)
    if ind.metric == "avg_change_3":
        return avg_change(obs, 3)
    if ind.metric == "yoy_gap":
        return yoy_gap(obs, compare_obs) if compare_obs else None
    raise ValueError(f"Unknown metric {ind.metric}")


# --- Scoring ------------------------------------------------------------------

def classify(ind, value):
    if value is None:
        return None
    if ind.higher_is_worse:
        if value >= ind.red:
            return RED
        return YELLOW if value >= ind.yellow else GREEN
    if value <= ind.red:
        return RED
    return YELLOW if value <= ind.yellow else GREEN


def is_stale(ind, latest_date, today):
    return (today - latest_date).days > ind.stale_days


def category_status(statuses):
    """Average the signals in a category: mostly red -> red, any meaningful stress -> yellow."""
    scored = [SCORES[s] for s in statuses if s]
    if not scored:
        return None
    avg = sum(scored) / len(scored)
    if avg >= 1.5:
        return RED
    return YELLOW if avg >= 0.5 else GREEN


VERDICTS = {
    "clear": (GREEN, "All clear", "No meaningful cluster of credit or debt stress. Conditions look healthy."),
    "watch": (YELLOW, "Watch", "Some signals are flashing, but stress isn't broad-based yet. Keep an eye on the red and yellow areas."),
    "warning": (RED, "Warning", "Stress signals are clustering across several areas. Conditions consistent with a downturn are building."),
    "severe": (RED, "High risk: deleveraging signals", "Most areas are flashing red at once: the cluster pattern that tends to accompany deleveraging or a downturn."),
}


def overall_verdict(category_statuses):
    statuses = [s for s in category_statuses if s]
    reds = statuses.count(RED)
    yellows = statuses.count(YELLOW)
    if reds >= 4:
        key = "severe"
    elif reds >= 2:
        key = "warning"
    elif reds == 1 or yellows >= 3:
        key = "watch"
    else:
        key = "clear"
    color, title, text = VERDICTS[key]
    return {"level": key, "status": color, "title": title, "text": text,
            "red_categories": reds, "yellow_categories": yellows, "total_categories": len(statuses)}


def downsample(obs, max_points=120):
    """Thin a long series for the sparkline, always keeping the latest point."""
    if len(obs) <= max_points:
        return obs
    step = len(obs) / max_points
    picked = [obs[int(i * step)] for i in range(max_points - 1)]
    return picked + [obs[-1]]


def threshold_text(ind):
    if ind.higher_is_worse:
        return f"Yellow at {ind.yellow:g} or higher, red at {ind.red:g} or higher"
    return f"Yellow at {ind.yellow:g} or lower, red at {ind.red:g} or lower"

