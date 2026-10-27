import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_data  # noqa: E402
from indicators import (GREEN, INDICATORS, RED, YELLOW, Indicator, avg_change,  # noqa: E402
                        category_status, change_1y, classify, compute_metric, downsample,
                        overall_verdict, yoy_gap, yoy_pct)


def ind(**overrides):
    base = dict(id="x", name="x", series="X", category="c", metric="level", unit="",
                yellow=10, red=30, higher_is_worse=True, stale_days=30, why="")
    base.update(overrides)
    return Indicator(**base)


def monthly(values, start=date(2020, 1, 1)):
    out, d = [], start
    for v in values:
        out.append((d, float(v)))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


class MetricTests(unittest.TestCase):
    def test_change_1y(self):
        self.assertAlmostEqual(change_1y(monthly(range(13))), 12)

    def test_yoy_pct(self):
        obs = monthly([100] + [0] * 11 + [105])
        self.assertAlmostEqual(yoy_pct(obs), 5)

    def test_yoy_needs_a_year_of_history(self):
        self.assertIsNone(yoy_pct(monthly([1, 2, 3])))

    def test_avg_change(self):
        self.assertAlmostEqual(avg_change(monthly([100, 103, 106, 112]), 3), 4)

    def test_yoy_gap_aligns_to_comparison_date(self):
        credit = monthly([100] * 12 + [103, 200])  # the last point is after the GDP date and must be ignored
        gdp = monthly([100] * 12 + [106])
        self.assertAlmostEqual(yoy_gap(credit, gdp), -3)

    def test_every_configured_metric_computes(self):
        obs = monthly(range(1, 40))
        for i in INDICATORS:
            self.assertIsNotNone(compute_metric(i, obs, obs), i.id)


class ScoringTests(unittest.TestCase):
    def test_higher_is_worse(self):
        i = ind()
        self.assertEqual([classify(i, v) for v in (5, 10, 29, 30)], [GREEN, YELLOW, YELLOW, RED])

    def test_lower_is_worse(self):
        i = ind(yellow=2, red=0, higher_is_worse=False)
        self.assertEqual([classify(i, v) for v in (3, 2, 1, 0, -1)], [GREEN, YELLOW, YELLOW, RED, RED])

    def test_missing_value(self):
        self.assertIsNone(classify(ind(), None))

    def test_category_status(self):
        self.assertEqual(category_status([GREEN, GREEN, RED]), YELLOW)
        self.assertEqual(category_status([RED, RED, YELLOW]), RED)
        self.assertEqual(category_status([GREEN, GREEN, YELLOW]), GREEN)
        self.assertIsNone(category_status([None]))

    def test_verdict_needs_a_cluster(self):
        self.assertEqual(overall_verdict([GREEN] * 6)["level"], "clear")
        self.assertEqual(overall_verdict([RED] + [GREEN] * 5)["level"], "watch")
        self.assertEqual(overall_verdict([YELLOW] * 3 + [GREEN] * 3)["level"], "watch")
        self.assertEqual(overall_verdict([RED] * 2 + [GREEN] * 4)["level"], "warning")
        self.assertEqual(overall_verdict([RED] * 4 + [GREEN] * 2)["level"], "severe")

    def test_downsample_keeps_latest(self):
        obs = monthly(range(500))
        thin = downsample(obs, 50)
        self.assertEqual(len(thin), 50)
        self.assertEqual(thin[-1], obs[-1])


class EndToEndTest(unittest.TestCase):
    """Runs fetch_data.main() against a fake FRED API (synthetic test data only)."""

    def fake_fred(self, endpoint, **params):
        if endpoint == "series/observations":
            if params["series_id"] == "DRTSCILM":
                raise OSError("simulated outage")
            start = date.today() - timedelta(days=800)
            return {"observations": [
                {"date": (start + timedelta(days=30 * i)).isoformat(), "value": str(1 + i)}
                for i in range(27)] + [{"date": date.today().isoformat(), "value": "."}]}
        if endpoint == "series":
            return {"seriess": [{"title": "Test", "frequency": "Monthly", "units": "Percent",
                                 "last_updated": "2026-01-01"}]}
        if endpoint == "series/release":
            return {"releases": [{"id": 1, "name": "Test Release", "link": "https://example.com"}]}
        if endpoint == "release/dates":
            return {"release_dates": [{"date": (date.today() + timedelta(days=3)).isoformat()}]}
        raise AssertionError(endpoint)

    def test_main_writes_dashboard_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data.json"
            with mock.patch.object(fetch_data, "fred", self.fake_fred), \
                    mock.patch.object(fetch_data, "OUTPUT", out), \
                    mock.patch.dict(os.environ, {"FRED_API_KEY": "test"}):
                fetch_data.main()
            data = json.loads(out.read_text())
        self.assertEqual(len(data["categories"]), 6)
        self.assertEqual(len(data["errors"]), 1)
        self.assertIn(data["verdict"]["level"], {"clear", "watch", "warning", "severe"})
        self.assertEqual(len(data["calendar"]), 1)
        all_inds = [i for c in data["categories"] for i in c["indicators"]]
        self.assertEqual(len(all_inds), len(INDICATORS))


if __name__ == "__main__":
    unittest.main()
