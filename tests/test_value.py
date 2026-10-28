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
from value_rules import (FAIL, NA, PASS, discount_rate_for, evaluate, growth_estimate, implied_growth,  # noqa: E402
                         intrinsic_value, is_hidden_gem, owner_earnings, present_value, quality_checks)


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
        self.assertLessEqual(intrinsic_value(compounder(growth=0.40))["growth_used"], 15.0)

    def test_discount_rate_follows_treasury_with_floor(self):
        self.assertAlmostEqual(discount_rate_for(5.0), 0.09)
        self.assertAlmostEqual(discount_rate_for(2.0), 0.08)   # floor
        self.assertAlmostEqual(discount_rate_for(None), 0.09)  # default

    def test_owner_earnings_uses_median_margin_on_latest_revenue(self):
        # Margins 20%, 5% (one-off hit), 22% -> median 20% of the latest revenue 500.
        years = [year(0, rev=400, fcf=80), year(1, rev=450, fcf=22.5), year(2, rev=500, fcf=110)]
        self.assertAlmostEqual(owner_earnings(years), 100.0)

    def test_owner_earnings_without_revenue_falls_back_to_average(self):
        years = [dict(year(i, fcf=f), revenue=None) for i, f in enumerate((10, 20, 30))]
        self.assertAlmostEqual(owner_earnings(years), 20.0)

    def test_growth_averages_revenue_and_eps(self):
        years = [year(i, rev=100 * 1.10 ** i, ni=100 * 1.02 ** i) for i in range(10)]
        self.assertAlmostEqual(growth_estimate(years), 0.06, places=3)

    def test_implied_growth_round_trip(self):
        price = present_value(2.0, 0.07, 0.09)
        self.assertAlmostEqual(implied_growth(price, 2.0, 0.09), 7.0, places=3)
        self.assertIsNone(implied_growth(price * 1000, 2.0, 0.09))  # beyond any plausible growth
        self.assertIsNone(implied_growth(price, -1.0, 0.09))        # no owner earnings

    def test_no_value_without_positive_cash_flow(self):
        years = [year(i, fcf=-10) for i in range(5)]
        self.assertIsNone(intrinsic_value(years))


class VerdictTests(unittest.TestCase):
    def test_buy_watch_and_avoid(self):
        years = compounder()
        iv = intrinsic_value(years, discount_rate_for(5.0))["per_share"]
        self.assertEqual(evaluate(years, iv * 0.5, 5.0)["verdict"], "buy")
        result = evaluate(years, iv * 1.2, 5.0)
        self.assertEqual(result["verdict"], "watch")
        self.assertEqual(result["valuation"]["discount_rate"], 9.0)
        self.assertGreater(result["valuation"]["implied_growth"], result["valuation"]["growth_used"])
        bad = [year(i, ni=(-10 if i % 2 else 10), fcf=-5, gp=50) for i in range(8)]
        self.assertEqual(evaluate(bad, 10, 4.0)["verdict"], "avoid")

    def test_new_company_is_too_early(self):
        result = evaluate(compounder(2), 1.0, 4.0, ipo_date="2026-09-01", today=date(2026, 10, 28))
        self.assertEqual(result["verdict"], "too_early")
        self.assertEqual(result["lockup_end"], "2027-02-28")

    def test_tiny_value_per_share_does_not_crash(self):
        years = [year(i, ni=1e-4, fcf=1e-4, rev=4e-4, gp=2.4e-4, debt=0) for i in range(6)]
        self.assertEqual(evaluate(years, 5.0, None)["verdict"], "watch")

    def test_foreign_filer_skips_per_share_value(self):
        result = evaluate(compounder(), 1.0, 4.0, per_share_ok=False)
        self.assertEqual(result["verdict"], "watch")
        self.assertNotIn("buy_below", result["valuation"])
        self.assertNotIn("market_cap", result["valuation"])
        self.assertFalse(is_hidden_gem(result))

    def test_no_data(self):
        self.assertEqual(evaluate([], None, None)["verdict"], "no_data")


def fact(end, val, start=None, form="10-K", filed=None):
    f = {"end": end, "val": val, "form": form, "filed": filed or end[:4] + "-02-15"}
    if start:
        f["start"] = start
    return f


class HiddenGemTests(unittest.TestCase):
    def gem(self, verdict="watch", cap=2e9, growth=15.0):
        return {"verdict": verdict, "valuation": {"market_cap": cap, "revenue_growth": growth}}

    def test_screen(self):
        self.assertTrue(is_hidden_gem(self.gem()))
        self.assertTrue(is_hidden_gem(self.gem(verdict="buy")))
        self.assertFalse(is_hidden_gem(self.gem(verdict="avoid")))
        self.assertFalse(is_hidden_gem(self.gem(cap=50e9)))   # too big to be under the radar
        self.assertFalse(is_hidden_gem(self.gem(cap=20e6)))   # micro-cap
        self.assertFalse(is_hidden_gem(self.gem(growth=4.0)))  # not growing fast enough

    def test_evaluate_reports_cap_and_growth(self):
        val = evaluate(compounder(), 10.0, 4.0)["valuation"]
        self.assertEqual(val["market_cap"], 1000)
        self.assertAlmostEqual(val["revenue_growth"], 8.0, places=0)


class DiscoveryTests(unittest.TestCase):
    def test_pick_batch_prefers_unscanned_then_oldest(self):
        universe = {t: (i, t) for i, t in enumerate(["A", "B", "C", "D", "E"])}
        scanned = {"A": "2026-10-01", "B": "2026-07-01", "C": "2026-10-27"}
        batch = fetch_companies.pick_batch(universe, scanned, date(2026, 10, 28), 3)
        self.assertEqual(sorted(batch[:2]), ["D", "E"])  # never scanned
        self.assertEqual(batch[2], "B")                   # oldest scan; A and C are recent

    def test_listed_universe_filters(self):
        data = {"fields": ["cik", "name", "ticker", "exchange"], "data": [
            [1, "Alpha", "ALP", "Nasdaq"], [1, "Alpha", "ALPWW", "Nasdaq"], [2, "Beta", "BET-PA", "NYSE"],
            [3, "Gamma", "GAM", "OTC"], [4, "Delta", "DEL", "NYSE"], [5, "Watched", "WAT", "NYSE"]]}
        with mock.patch.object(fetch_companies, "get_json", return_value=data):
            self.assertEqual(fetch_companies.listed_universe({"WAT"}), {"ALP": (1, "Alpha"), "DEL": (4, "Delta")})


class SecParsingTests(unittest.TestCase):
    def test_foreign_filer(self):
        f20 = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [fact("2025-12-31", 5, "2025-01-01", form="20-F")]}}}}}
        f10 = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [fact("2025-12-31", 5, "2025-01-01")]}}}}}
        self.assertTrue(fetch_companies.foreign_filer(f20))
        self.assertFalse(fetch_companies.foreign_filer(f10))

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

    def test_stock_split_is_restated(self):
        # 4-for-1 split between 2020 and 2021: old filings keep pre-split shares and EPS.
        years = [{"end": f"{y}-12-31", "net_income": 100.0 + y - 2018, "eps": None, "shares": None} for y in range(2018, 2023)]
        for y in years:
            split = y["end"] >= "2021"
            y["shares"] = 400.0 if split else 100.0
            y["eps"] = y["net_income"] / y["shares"]
        fetch_companies.adjust_for_splits(years)
        self.assertEqual([y["shares"] for y in years], [400.0] * 5)
        self.assertAlmostEqual(years[0]["eps"], 100 / 400)

    def test_split_blurred_by_buybacks_is_detected(self):
        # 15-for-1 split, with ~9% fewer shares after buybacks: ratio is about 13.6.
        years = [{"end": "2022-12-31", "shares": 65.0, "eps": 30.0}, {"end": "2023-12-31", "shares": 885.0, "eps": 2.5}]
        fetch_companies.adjust_for_splits(years)
        self.assertEqual(years[0]["shares"], 975.0)
        self.assertAlmostEqual(years[0]["eps"], 2.0)

    def test_ordinary_dilution_is_not_a_split(self):
        years = [{"end": "2020-12-31", "shares": 100.0, "eps": 1.0}, {"end": "2021-12-31", "shares": 130.0, "eps": 1.0}]
        fetch_companies.adjust_for_splits(years)
        self.assertEqual(years[0]["shares"], 100.0)

    def test_repair_mis_scaled_and_missing_shares(self):
        years = [{"end": "2024-12-31", "net_income": 8e9, "eps": 11.0, "shares": 731.0},   # filed in millions
                 {"end": "2025-12-31", "net_income": 5e9, "eps": None, "shares": None}]    # multi-class: no total
        cover = {"2026-02-01": 2e9, "2027-01-01": 9e9}
        fetch_companies.repair_shares(years, cover)
        self.assertAlmostEqual(years[0]["shares"], 8e9 / 11)
        self.assertEqual(years[1]["shares"], 2e9)
        self.assertAlmostEqual(years[1]["eps"], 2.5)

    def test_cover_shares_sums_classes(self):
        facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2026-02-01", "val": 150, "accn": "a1", "filed": "2026-02-10"},
            {"end": "2026-02-01", "val": 60, "accn": "a1", "filed": "2026-02-10"}]}}}}}
        self.assertEqual(fetch_companies._cover_shares(facts), {"2026-02-01": 210})

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
        if url.endswith("company_tickers_exchange.json"):
            return json.dumps({"data": [[1, "Good Co", "GOOD", "NYSE"], [3, "Small Grower", "SMOL", "Nasdaq"],
                                        [4, "Junk Co", "JUNK", "NYSE"]]}).encode()
        if "companyfacts/CIK0000000003" in url:
            years = range(2018, 2026)
            ni = [fact(f"{y}-12-31", 10e6 * 1.2 ** (y - 2018), f"{y}-01-01") for y in years]
            return json.dumps({"entityName": "Small Grower", "facts": {"us-gaap": {
                "NetIncomeLoss": {"units": {"USD": ni}},
                "Revenues": {"units": {"USD": [dict(f, val=f["val"] * 4) for f in ni]}},
                "GrossProfit": {"units": {"USD": [dict(f, val=f["val"] * 2.5) for f in ni]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [dict(f, val=f["val"] * 1.1) for f in ni]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [dict(f, val=f["val"] / 1e8) for f in ni]}},
                "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [dict(f, val=1e8) for f in ni]}},
            }}}).encode()
        if "companyfacts/CIK0000000004" in url:
            raise fetch_companies.urllib.error.HTTPError(url, 404, "nf", {}, None)
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
            out, wl, disc = Path(tmp) / "companies.json", Path(tmp) / "watchlist.txt", Path(tmp) / "discovery.json"
            wl.write_text("GOOD  # good co\nMISSING\n")
            with mock.patch.object(fetch_companies, "get", self.fake_get), \
                    mock.patch.object(fetch_companies, "OUTPUT", out), \
                    mock.patch.object(fetch_companies, "WATCHLIST", wl), \
                    mock.patch.object(fetch_companies, "DISCOVERY_OUTPUT", disc), \
                    mock.patch.dict(os.environ, {"FRED_API_KEY": ""}):
                fetch_companies.main()
            data = json.loads(out.read_text())
            discovery = json.loads(disc.read_text())
        self.assertEqual([c["ticker"] for c in data["watchlist"]], ["GOOD"])
        self.assertIn(data["watchlist"][0]["verdict"], {"buy", "watch"})
        self.assertEqual(data["ipos"][0]["ticker"], "BNEW")
        self.assertEqual(data["ipos"][0]["verdict"], "no_data")
        self.assertEqual(data["errors"][0]["ticker"], "MISSING")
        # Watchlist ticker GOOD is excluded from discovery; JUNK has no financials.
        self.assertEqual(sorted(discovery["scanned"]), ["JUNK", "SMOL"])
        self.assertEqual([c["ticker"] for c in discovery["candidates"]], ["SMOL"])


class WatchlistOnlyTest(EndToEndTest):
    def test_main(self):
        """Watchlist-only runs rescore watchlist.txt, keep the previous IPOs and skip discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            out, wl, disc = Path(tmp) / "companies.json", Path(tmp) / "watchlist.txt", Path(tmp) / "discovery.json"
            wl.write_text("GOOD\n")
            out.write_text(json.dumps({"ipos": [{"ticker": "OLDIPO"}], "watchlist": [{"ticker": "GONE"}],
                                       "errors": [{"ticker": "OLDIPO", "error": "x"}, {"ticker": "GONE", "error": "y"}]}))
            seen = []

            def fake_get(url, ua=None, sec=True):
                seen.append(url)
                return self.fake_get(url, ua, sec)
            with mock.patch.object(fetch_companies, "get", fake_get), \
                    mock.patch.object(fetch_companies, "OUTPUT", out), \
                    mock.patch.object(fetch_companies, "WATCHLIST", wl), \
                    mock.patch.object(fetch_companies, "DISCOVERY_OUTPUT", disc), \
                    mock.patch.dict(os.environ, {"FRED_API_KEY": ""}):
                fetch_companies.main(watchlist_only=True)
            data = json.loads(out.read_text())
        self.assertEqual([c["ticker"] for c in data["watchlist"]], ["GOOD"])
        self.assertEqual(data["ipos"], [{"ticker": "OLDIPO"}])
        self.assertEqual(data["errors"], [{"ticker": "OLDIPO", "error": "x"}])
        self.assertFalse(disc.exists())
        self.assertFalse(any("form.idx" in u or "exchange" in u for u in seen))


if __name__ == "__main__":
    unittest.main()
