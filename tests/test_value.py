import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_companies  # noqa: E402
from value_rules import FAIL, NA, PASS, evaluate, intrinsic_value, quality_checks  # noqa: E402


def year(n, ni=100.0, rev=400.0, gp=240.0, fcf=95.0, capex=20.0, equity=500.0, debt=200.0, eps=None, shares=100.0):
    return {"end": f"{2015 + n}-12-31", "net_income": ni, "revenue": rev, "gross_profit": gp, "fcf": fcf,
            "capex": capex, "equity": equity, "debt": debt, "eps": eps if eps is not None else ni / shares,
            "shares": shares}


def compounder(n=10, growth=0.08):
    """A steady, high-quality business growing ~8% a year (synthetic test data)."""
    return [year(i, ni=100 * (1 + growth) ** i, rev=400 * (1 + growth) ** i, gp=240 * (1 + growth) ** i,
                 fcf=95 * (1 + growth) ** i) for i in range(n)]


def by_key(checks):
    return {c["key"]: c["status"] for c in checks}


class QualityCheckTests(unittest.TestCase):
    def test_quality_business_passes_everything(self):
        self.assertEqual(set(by_key(quality_checks(compounder())).values()), {PASS})

    def test_a_loss_fails_consistency(self):
        years = compounder()
        years[4]["net_income"] = -5
        self.assertEqual(by_key(quality_checks(years))["profits"], FAIL)

    def test_short_history_is_not_judged_on_consistency(self):
        self.assertEqual(by_key(quality_checks(compounder(3)))["profits"], NA)

    def test_heavy_debt_fails(self):
        years = compounder()
        years[-1]["debt"] = years[-1]["net_income"] * 6
        self.assertEqual(by_key(quality_checks(years))["debt"], FAIL)

    def test_debt_with_losses_fails(self):
        years = compounder()
        years[-1]["net_income"] = -1
        self.assertEqual(by_key(quality_checks(years))["debt"], FAIL)

    def test_low_margins_and_dilution(self):
        years = [year(i, gp=60, shares=100 * 1.05 ** i) for i in range(6)]
        checks = by_key(quality_checks(years))
        self.assertEqual(checks["gross_margin"], FAIL)
        self.assertEqual(checks["dilution"], FAIL)

    def test_negative_equity_skips_roe(self):
        years = [year(i, equity=-50) for i in range(6)]
        self.assertEqual(by_key(quality_checks(years))["roe"], NA)


class ValuationTests(unittest.TestCase):
    def test_intrinsic_value_grows_with_growth(self):
        slow = intrinsic_value(compounder(growth=0.02))["per_share"]
        fast = intrinsic_value(compounder(growth=0.08))["per_share"]
        self.assertGreater(fast, slow)

    def test_growth_is_capped(self):
        self.assertLessEqual(intrinsic_value(compounder(growth=0.40))["growth_used"], 12.0)

    def test_no_value_without_positive_cash_flow(self):
        years = [year(i, fcf=-10) for i in range(5)]
        self.assertIsNone(intrinsic_value(years))


class VerdictTests(unittest.TestCase):
    def test_buy_watch_and_avoid(self):
        years = compounder()
        iv = intrinsic_value(years)["per_share"]
        self.assertEqual(evaluate(years, iv * 0.5, 4.0)["verdict"], "buy")
        self.assertEqual(evaluate(years, iv * 1.2, 4.0)["verdict"], "watch")
        bad = [year(i, ni=(-10 if i % 2 else 10), fcf=-5, gp=50) for i in range(8)]
        self.assertEqual(evaluate(bad, 10, 4.0)["verdict"], "avoid")

    def test_new_company_is_too_early(self):
        result = evaluate(compounder(2), 1.0, 4.0, ipo_date="2026-09-01", today=date(2026, 10, 28))
        self.assertEqual(result["verdict"], "too_early")
        self.assertEqual(result["lockup_end"], "2027-02-28")

    def test_no_data(self):
        self.assertEqual(evaluate([], None, None)["verdict"], "no_data")


def fact(end, val, start=None, form="10-K", filed=None):
    f = {"end": end, "val": val, "form": form, "filed": filed or end[:4] + "-02-15"}
    if start:
        f["start"] = start
    return f


class SecParsingTests(unittest.TestCase):
    def test_annual_table_picks_full_years_and_fills_gaps(self):
        facts = {"facts": {"us-gaap": {
            "NetIncomeLoss": {"units": {"USD": [
                fact("2024-12-31", 10, "2024-01-01"),
                fact("2024-12-31", 3, "2024-10-01", form="10-Q"),           # quarter: ignored
                fact("2024-12-31", 12, "2024-01-01", filed="2026-02-15"),  # restated later: wins
                fact("2025-12-31", 15, "2025-01-01")]}},
            "SalesRevenueNet": {"units": {"USD": [fact("2024-12-31", 90, "2024-01-01")]}},
            "Revenues": {"units": {"USD": [fact("2025-12-31", 110, "2025-01-01")]}},
            "CostOfRevenue": {"units": {"USD": [fact("2025-12-31", 50, "2025-01-01")]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fact("2025-12-31", 20, "2025-01-01")]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact("2025-12-31", 4, "2025-01-01")]}},
            "StockholdersEquity": {"units": {"USD": [fact("2025-12-31", 70)]}},
        }}}
        years = fetch_companies.annual_table(facts)
        self.assertEqual([y["end"] for y in years], ["2024-12-31", "2025-12-31"])
        self.assertEqual(years[0]["net_income"], 12)
        self.assertEqual(years[0]["revenue"], 90)
        self.assertEqual(years[1]["gross_profit"], 60)
        self.assertEqual(years[1]["fcf"], 16)
        self.assertEqual(years[1]["equity"], 70)

    def test_parse_form_index(self):
        text = """Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------
424B3            OTHER CO                                                      1111111     2026-07-02  edgar/data/1111111/a.txt
424B4            NEW CO INC.                                                   2222222     2026-07-10  edgar/data/2222222/b.txt
424B4            NEW CO INC.                                                   2222222     2026-07-08  edgar/data/2222222/c.txt
424B4            OLD DEAL CORP                                                 3333333     2024-01-01  edgar/data/3333333/d.txt
"""
        self.assertEqual(fetch_companies.parse_form_index(text, date(2025, 10, 28), date(2026, 10, 28)),
                         {2222222: "2026-07-08"})

    def submissions(self, forms, sic="7372", tickers=("NEWC", "NEWCW"), exchanges=("Nasdaq", "Nasdaq")):
        return {"sic": sic, "tickers": list(tickers), "exchanges": list(exchanges),
                "filings": {"recent": {"form": [f for f, _ in forms], "filingDate": [d for _, d in forms]},
                            "files": []}}

    def test_true_ipo_detected(self):
        sub = self.submissions([("10-Q", "2026-09-01"), ("424B4", "2026-07-08"), ("S-1", "2026-05-01")])
        self.assertEqual(fetch_companies.ipo_from_submissions(sub, "2026-07-08"), ("NEWC", "Nasdaq"))

    def test_follow_on_offering_rejected(self):
        sub = self.submissions([("424B4", "2026-07-08"), ("S-1", "2026-05-01"), ("10-K", "2026-02-01")])
        self.assertIsNone(fetch_companies.ipo_from_submissions(sub, "2026-07-08"))

    def test_spac_and_unlisted_rejected(self):
        forms = [("424B4", "2026-07-08"), ("S-1", "2026-05-01")]
        self.assertIsNone(fetch_companies.ipo_from_submissions(self.submissions(forms, sic="6770"), "2026-07-08"))
        self.assertIsNone(fetch_companies.ipo_from_submissions(self.submissions(forms, exchanges=("", "")), "2026-07-08"))


class EndToEndTest(unittest.TestCase):
    """fetch_companies.main() against fake SEC/price responses (synthetic test data only)."""

    def fake_get(self, url, ua=None, sec=True):
        if url.endswith("company_tickers.json"):
            return json.dumps({"0": {"cik_str": 1, "ticker": "GOOD", "title": "Good Co"}}).encode()
        if "companyfacts/CIK0000000001" in url:
            ni = [fact(f"{y}-12-31", 100 + 10 * (y - 2016), f"{y}-01-01") for y in range(2016, 2026)]
            return json.dumps({"entityName": "Good Co", "facts": {"us-gaap": {
                "NetIncomeLoss": {"units": {"USD": ni}},
                "Revenues": {"units": {"USD": [dict(f, val=f["val"] * 4) for f in ni]}},
                "GrossProfit": {"units": {"USD": [dict(f, val=f["val"] * 2.5) for f in ni]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [dict(f, val=f["val"] * 1.1) for f in ni]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [dict(f, val=f["val"] / 100) for f in ni]}},
                "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [dict(f, val=100) for f in ni]}},
            }}}).encode()
        if "companyfacts/CIK0000000002" in url:
            raise fetch_companies.urllib.error.HTTPError(url, 404, "nf", {}, None)
        if "form.idx" in url:
            return b"424B4            BRAND NEW INC                         2     2026-09-15  edgar/data/2/x.txt\n"
        if "submissions/CIK0000000002" in url:
            return json.dumps({"name": "Brand New Inc", "sic": "7372", "sicDescription": "Software",
                               "tickers": ["BNEW"], "exchanges": ["NYSE"],
                               "filings": {"recent": {"form": ["424B4", "S-1"],
                                                      "filingDate": ["2026-09-15", "2026-08-01"]}}}).encode()
        if "finance.yahoo.com" in url:
            return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 12.5},
                                                     "timestamp": [1789000000],
                                                     "indicators": {"quote": [{"close": [12.5]}]}}]}}).encode()
        raise AssertionError(url)

    def test_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, wl = Path(tmp) / "companies.json", Path(tmp) / "watchlist.txt"
            wl.write_text("GOOD  # good co\nMISSING\n")
            with mock.patch.object(fetch_companies, "get", self.fake_get), \
                    mock.patch.object(fetch_companies, "OUTPUT", out), \
                    mock.patch.object(fetch_companies, "WATCHLIST", wl), \
                    mock.patch.dict(os.environ, {"FRED_API_KEY": ""}):
                fetch_companies.main()
            data = json.loads(out.read_text())
        self.assertEqual([c["ticker"] for c in data["watchlist"]], ["GOOD"])
        self.assertIn(data["watchlist"][0]["verdict"], {"buy", "watch"})
        self.assertEqual(data["ipos"][0]["ticker"], "BNEW")
        self.assertEqual(data["ipos"][0]["verdict"], "no_data")
        self.assertEqual(data["errors"][0]["ticker"], "MISSING")


if __name__ == "__main__":
    unittest.main()
