import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_companies  # noqa: E402
import news_check  # noqa: E402

TODAY = date(2026, 10, 28)


class PriceTrendTests(unittest.TestCase):
    def test_drop_from_high_and_six_month_change(self):
        points = [((TODAY - timedelta(days=300)).isoformat(), 700.0),
                  ((TODAY - timedelta(days=180)).isoformat(), 500.0),
                  (TODAY.isoformat(), 350.0)]
        trend = news_check.price_trend(points, TODAY)
        self.assertEqual(trend["below_high"], 50.0)
        self.assertEqual(trend["high_52w"], 700.0)
        self.assertEqual(trend["change_6m"], -30.0)

    def test_ignores_prices_older_than_a_year(self):
        points = [((TODAY - timedelta(days=500)).isoformat(), 1000.0), ((TODAY - timedelta(days=30)).isoformat(), 100.0),
                  (TODAY.isoformat(), 100.0)]
        self.assertEqual(news_check.price_trend(points, TODAY)["below_high"], 0.0)

    def test_not_enough_data(self):
        self.assertEqual(news_check.price_trend([(TODAY.isoformat(), 1.0)], TODAY), {})


class FilingTests(unittest.TestCase):
    submissions = {"filings": {"recent": {
        "form": ["8-K", "10-Q", "8-K", "8-K", "8-K"],
        "filingDate": ["2026-10-01", "2026-09-01", "2026-08-20", "2026-05-21", "2025-01-01"],
        "items": ["2.02,9.01", "", "4.02", "2.05,5.02", "3.01"],
        "accessionNumber": ["0001-26-1", "0001-26-2", "0001-26-3", "0001-26-4", "0001-25-5"],
        "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm", "e.htm"],
    }}}

    def test_recent_8k_items_newest_first(self):
        filings = news_check.recent_8k(self.submissions, 896878, TODAY)
        self.assertEqual([f["date"] for f in filings], ["2026-10-01", "2026-08-20", "2026-05-21"])  # 2025 filing too old
        self.assertEqual([i["code"] for i in filings[0]["items"]], ["2.02"])  # 9.01 (exhibits) isn't listed
        self.assertEqual(filings[1]["url"], "https://www.sec.gov/Archives/edgar/data/896878/0001263/c.htm")

    def test_flags_put_red_first(self):
        filings = news_check.recent_8k(self.submissions, 1, TODAY)
        flags = news_check.flags_for({"below_high": 30.0, "high_52w": 700.0}, filings)
        self.assertEqual([f["level"] for f in flags], ["red", "yellow", "yellow", "yellow"])
        self.assertIn("restatement", flags[0]["text"])
        self.assertIn("Down 30%", flags[1]["text"])

    def test_big_drop_is_red_and_small_moves_are_ignored(self):
        self.assertEqual(news_check.flags_for({"below_high": 52.0, "high_52w": 700.0}, [])[0]["level"], "red")
        self.assertEqual(news_check.flags_for({"below_high": 10.0, "high_52w": 700.0}, []), [])


class HeadlineTests(unittest.TestCase):
    rss = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Intuit shares slide on AI fears - Reuters</title><link>https://news.example/a</link>
        <pubDate>Mon, 26 Oct 2026 14:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
      <item><title>Older story - Forbes</title><link>https://news.example/b</link>
        <pubDate>Fri, 02 Oct 2026 09:00:00 GMT</pubDate><source url="https://forbes.com">Forbes</source></item>
      <item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Fri, 02 Oct 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""

    def test_parse_strips_source_and_rejects_unsafe_links(self):
        items = news_check.parse_headlines(self.rss)
        self.assertEqual([h["title"] for h in items], ["Intuit shares slide on AI fears", "Older story"])
        self.assertEqual(items[0], {"title": "Intuit shares slide on AI fears", "source": "Reuters",
                                    "date": "2026-10-26", "url": "https://news.example/a"})

    def test_search_name(self):
        self.assertEqual(news_check.search_name("INTUIT INC."), "Intuit")
        self.assertEqual(news_check.search_name("Moody's Corporation"), "Moody's")
        self.assertEqual(news_check.search_name("COSTCO WHOLESALE CORP /NEW"), "Costco Wholesale")
        self.assertIn("%22Intuit%22", news_check.headlines_url("INTUIT INC."))


class AttachTests(unittest.TestCase):
    def test_only_buy_candidates_are_checked_and_failures_are_contained(self):
        entries = [{"ticker": "BUYR", "cik": 1, "name": "Buyer Inc", "verdict": "buy"},
                   {"ticker": "WAIT", "cik": 2, "name": "Waiter Inc", "verdict": "watch"}]
        with mock.patch.object(fetch_companies, "yahoo_chart", side_effect=OSError("down")), \
                mock.patch.object(fetch_companies, "get_json", return_value=FilingTests.submissions), \
                mock.patch.object(fetch_companies, "get", return_value=HeadlineTests.rss):
            fetch_companies.attach_news_checks(entries, TODAY)
        check = entries[0]["news_check"]
        self.assertEqual(check["trend"], {})  # price source failed, the rest still worked
        self.assertEqual(len(check["filings"]), 3)
        self.assertEqual(len(check["headlines"]), 2)
        self.assertNotIn("news_check", entries[1])


if __name__ == "__main__":
    unittest.main()
