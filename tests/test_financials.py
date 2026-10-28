import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from value_rules import (NA, PASS, FAIL, book_value_estimate, evaluate, financial_checks,  # noqa: E402
                         implied_roe, is_financial_sic, is_hidden_gem)


def bank_year(n, ni=120.0, equity=1000.0, assets=10000.0, shares=100.0, preferred=0.0, growth=0.07):
    """A steady bank: ~12% ROE, 1.2% ROA, equity 10% of assets, book value compounding ~7% (synthetic)."""
    f = (1 + growth) ** n
    return {"end": f"{2016 + n}-12-31", "net_income": ni * f, "revenue": ni * f * 4, "equity": equity * f,
            "assets": assets * f, "shares": shares, "preferred": preferred, "eps": ni * f / shares,
            "fcf": -500.0 * f, "capex": 5.0, "gross_profit": None, "debt": 5000.0 * f}


def bank(n=10, **kw):
    return [bank_year(i, **kw) for i in range(n)]


class DetectionTests(unittest.TestCase):
    def test_industry_codes(self):
        for sic in ("6021", "6022", "6035", "6141", "6153", "6162", "6199", "6211", "6311", "6331", "6351", 6021):
            self.assertTrue(is_financial_sic(sic), sic)
        for sic in ("6411", "6282", "6200", "6798", "7372", "", None, "n/a"):
            self.assertFalse(is_financial_sic(sic), sic)


class FinancialCheckTests(unittest.TestCase):
    def test_steady_bank_passes_and_cash_flow_checks_are_replaced(self):
        checks = {c["key"]: c for c in financial_checks(bank())}
        self.assertEqual(set(checks), {"profits", "roe", "roa", "equity_assets", "book_growth",
                                       "net_margin", "growth", "dilution"})
        self.assertTrue(all(c["status"] == PASS for c in checks.values()), {k: c["status"] for k, c in checks.items()})
        self.assertAlmostEqual(checks["roa"]["value"], 1.2)
        self.assertAlmostEqual(checks["equity_assets"]["value"], 10.0)
        self.assertAlmostEqual(checks["book_growth"]["value"], 7.0, places=1)

    def test_thin_capital_and_low_returns_fail(self):
        checks = {c["key"]: c["status"] for c in financial_checks(bank(ni=40.0, assets=20000.0))}
        self.assertEqual(checks["roe"], FAIL)           # 4% ROE
        self.assertEqual(checks["roa"], FAIL)           # 0.2% ROA
        self.assertEqual(checks["equity_assets"], FAIL)  # 5% equity

    def test_missing_assets_is_not_judged(self):
        years = [dict(y, assets=None) for y in bank()]
        checks = {c["key"]: c["status"] for c in financial_checks(years)}
        self.assertEqual(checks["roa"], NA)
        self.assertEqual(checks["equity_assets"], NA)


class BookValueTests(unittest.TestCase):
    def test_justified_price_to_book(self):
        years = bank(ni=150.0)  # 15% ROE
        est = book_value_estimate(years, 0.09)
        self.assertAlmostEqual(est["justified_pb"], (0.15 - 0.03) / (0.09 - 0.03))  # 2.0x book
        self.assertAlmostEqual(est["per_share"], 2.0 * years[-1]["equity"] / 100)

    def test_preferred_stock_is_excluded_from_book(self):
        plain = book_value_estimate(bank(), 0.09)["book_value_per_share"]
        with_pref = book_value_estimate(bank(preferred=100.0), 0.09)["book_value_per_share"]
        self.assertAlmostEqual(plain - with_pref, 1.0)

    def test_roe_is_capped_and_low_roe_is_worth_little(self):
        self.assertAlmostEqual(book_value_estimate(bank(ni=500.0), 0.09)["justified_pb"], (0.25 - 0.03) / 0.06)
        self.assertEqual(book_value_estimate(bank(ni=20.0), 0.09)["justified_pb"], 0.0)  # 2% ROE < growth

    def test_implied_roe_round_trip(self):
        # At 2x book with a 9% required return, the price assumes a 15% sustained ROE.
        self.assertAlmostEqual(implied_roe(20.0, 10.0, 0.09), 15.0)


class EvaluateTests(unittest.TestCase):
    def test_financial_uses_book_method(self):
        years = bank(ni=150.0)
        bvps = years[-1]["equity"] / 100
        result = evaluate(years, bvps * 1.2, 5.0, financial=True)
        val = result["valuation"]
        self.assertEqual(result["valuation_method"], "book")
        self.assertEqual(result["verdict"], "buy")  # 1.2x book against a 2.0x justified multiple (buy-below 1.5x)
        self.assertEqual(val["price_to_book"], 1.2)
        self.assertAlmostEqual(val["implied_roe"], 10.2)
        self.assertNotIn("owner_earnings_yield", val)
        self.assertNotIn("implied_growth", val)
        self.assertTrue(any("book value" in n for n in result["notes"]))

    def test_same_bank_on_cash_flow_would_be_misjudged(self):
        # Negative "free cash flow" (loans made) fails a non-financial screen: why banks need their own method.
        self.assertEqual(evaluate(bank(ni=150.0), 30.0, 5.0)["verdict"], "avoid")

    def test_financial_market_cap_still_feeds_discovery(self):
        result = evaluate(bank(ni=150.0, growth=0.12), 20.0, 5.0, financial=True)
        self.assertIn("market_cap", result["valuation"])
        self.assertTrue(is_hidden_gem(dict(result, valuation=dict(result["valuation"], market_cap=1e9))))


if __name__ == "__main__":
    unittest.main()
