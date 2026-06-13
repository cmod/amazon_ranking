"""
Regression tests for amazon.py's HTML extraction + signature logic.

Run:
    ./venv/bin/python -m unittest test_amazon.py
    # or
    ./venv/bin/python test_amazon.py
"""
from __future__ import annotations

import os
import unittest

from bs4 import BeautifulSoup

import amazon


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestAmazonReviewCount(unittest.TestCase):
    def test_regression_star_rating_does_not_fuse_with_count(self):
        # Regression for the 2026-04-24 bug: Amazon's reviews-medley-widget
        # concatenates "4 out of 5" (star rating) with "53 global ratings"
        # (count) into "4 out of 553 global ratings" after whitespace strip.
        # The old fuzzy regex captured 553 instead of 53. The fix uses the
        # canonical [data-hook="total-review-count"] element, which contains
        # only the count text.
        html = """
        <div data-hook="reviews-medley-widget">
            Customer reviews 4 out of 5 stars 4 out of 5
            <span data-hook="total-review-count">53 global ratings</span>
        </div>
        """
        self.assertEqual(amazon.get_amazon_review_count(_soup(html)), "53")

    def test_two_digit_count(self):
        html = '<span data-hook="total-review-count">34 global ratings</span>'
        self.assertEqual(amazon.get_amazon_review_count(_soup(html)), "34")

    def test_three_digit_count(self):
        html = '<span data-hook="total-review-count">299 global ratings</span>'
        self.assertEqual(amazon.get_amazon_review_count(_soup(html)), "299")

    def test_comma_separated_count(self):
        html = '<span data-hook="total-review-count">1,234 global ratings</span>'
        self.assertEqual(amazon.get_amazon_review_count(_soup(html)), "1234")

    def test_fallback_to_acr_element(self):
        # If data-hook="total-review-count" is absent, fall back to
        # #acrCustomerReviewText which renders like "(53)" next to the stars.
        html = '<span id="acrCustomerReviewText">(53)</span>'
        self.assertEqual(amazon.get_amazon_review_count(_soup(html)), "53")

    def test_returns_none_when_missing(self):
        self.assertIsNone(amazon.get_amazon_review_count(_soup("<p>nothing</p>")))


class TestEntrySignature(unittest.TestCase):
    def test_ranking_order_invariant(self):
        a = {"amazon_review_count": "100", "rankings": [
            {"rank": "5", "category": "B"}, {"rank": "3", "category": "A"}]}
        b = {"amazon_review_count": "100", "rankings": [
            {"rank": "3", "category": "A"}, {"rank": "5", "category": "B"}]}
        self.assertEqual(amazon.entry_signature(a, False),
                         amazon.entry_signature(b, False))

    def test_crossed_ranks_produce_distinct_signatures(self):
        # Regression for the 2026-04-24 signature bug: sorting rankings by
        # (rank, category) collapsed this case to identical tuples, causing
        # false "no-change" dedupes when category ranks swapped. Sorting by
        # category (the stable identifier) must produce different signatures.
        a = {"amazon_review_count": "100", "rankings": [
            {"rank": "4", "category": "A"}, {"rank": "3", "category": "B"}]}
        b = {"amazon_review_count": "100", "rankings": [
            {"rank": "3", "category": "A"}, {"rank": "4", "category": "B"}]}
        self.assertNotEqual(amazon.entry_signature(a, False),
                            amazon.entry_signature(b, False))

    def test_norm_count_coerces_mixed_types(self):
        self.assertIsNone(amazon._norm_count(None))
        self.assertIsNone(amazon._norm_count(""))
        self.assertIsNone(amazon._norm_count("0"))
        self.assertIsNone(amazon._norm_count(0))
        self.assertEqual(amazon._norm_count("37"), 37)
        self.assertEqual(amazon._norm_count(37), 37)

    def test_has_goodreads_affects_signature(self):
        # has_goodreads=True appends two count slots; without it, those are
        # omitted. Same entry must hash differently under the two flags so
        # toggling goodreads_url in books.json doesn't produce false matches.
        e = {"amazon_review_count": "100", "rankings": []}
        self.assertNotEqual(amazon.entry_signature(e, False),
                            amazon.entry_signature(e, True))


class TestGoodreadsFlapping(unittest.TestCase):
    """Regression for the 2026-06-10 Goodreads WAF bug: Goodreads started
    serving an AWS WAF challenge (HTTP 202) to plain requests clients. A
    failed Goodreads fetch must not register as a data change, or the
    history fills with entries that alternately have and lack GR fields."""

    def _scrape_sequence(self, gr_runs):
        import json
        import logging
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        az = {"amazon_review_count": "100",
              "rankings": [{"rank": "5", "category": "Books"}]}
        book = {"slug": "sim", "display_name": "Sim",
                "amazon_url": "x", "goodreads_url": "y"}
        log = logging.getLogger("null")
        log.addHandler(logging.NullHandler())

        statuses = []
        with tempfile.TemporaryDirectory() as td:
            with patch.object(amazon, "DATA_DIR", Path(td)):
                for gr in gr_runs:
                    with patch.object(amazon, "get_amazon_data", return_value=dict(az)), \
                         patch.object(amazon, "get_goodreads_data", return_value=gr):
                        amazon.scrape_book(book, log)
                    env = json.loads((Path(td) / "sim.json").read_text())
                    statuses.append(env["last_attempt_status"])
        return statuses, env

    def test_failed_gr_fetch_is_not_a_change(self):
        gr = {"goodreads_ratings_count": "47", "goodreads_reviews_count": "21"}
        statuses, env = self._scrape_sequence([gr, None, gr])
        self.assertEqual(statuses, ["appended", "no-change", "no-change"])
        self.assertEqual(len(env["entries"]), 1)

    def test_real_gr_change_still_appends(self):
        gr1 = {"goodreads_ratings_count": "47", "goodreads_reviews_count": "21"}
        gr2 = {"goodreads_ratings_count": "50", "goodreads_reviews_count": "22"}
        statuses, env = self._scrape_sequence([gr1, None, gr2])
        self.assertEqual(statuses, ["appended", "no-change", "appended"])
        self.assertEqual(len(env["entries"]), 2)


class TestDashboardSmoke(unittest.TestCase):
    """Headless-render the dashboard template with synthetic data to catch
    JavaScript errors the Python tests cannot see.

    Regression for 2026-06-13: a wrong variable name in createCharts()
    (aggregatedEntries vs the in-scope entries) threw a ReferenceError that
    blanked every book page — every stat card and chart vanished — while all
    Python tests stayed green. This test executes the template's real JS and
    fails if the page throws or the metric sections render empty.

    Chart.js is stubbed so the test needs no network. Skips automatically
    when no Chrome/Chromium binary is present (e.g. minimal CI images)."""

    _MAC_CANDIDATES = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]

    def _find_chrome(self):
        import shutil
        for name in ("google-chrome", "google-chrome-stable", "chromium",
                     "chromium-browser", "chrome"):
            found = shutil.which(name)
            if found:
                return found
        for path in self._MAC_CANDIDATES:
            if os.path.exists(path):
                return path
        return None

    def _synthetic_envelope(self):
        # 3 days of data. Goodreads present days 1-2, absent on day 3 (the
        # AWS-WAF scenario) so the render must exercise the GR fallback and
        # null handling. Two ranking categories, multiple entries per day to
        # exercise the daily aggregation.
        def entry(ts, reviews, books_rank, photo_rank, gr_ratings=None, gr_reviews=None):
            e = {
                "timestamp": ts,
                "amazon_review_count": str(reviews),
                "rankings": [
                    {"rank": str(books_rank), "category": "Books"},
                    {"rank": str(photo_rank), "category": "Photo Essays"},
                ],
            }
            if gr_ratings is not None:
                e["goodreads_ratings_count"] = str(gr_ratings)
            if gr_reviews is not None:
                e["goodreads_reviews_count"] = str(gr_reviews)
            return e

        return {
            "slug": "smoke",
            "display_name": "Smoke Test Book",
            "last_successful_scrape": "2026-06-10 03:00:00",
            "last_error": None,
            "last_attempt_timestamp": "2026-06-10 03:00:00",
            "last_attempt_status": "no-change",
            "entries": [
                entry("2026-06-08 03:00:00", 100, 5000, 20, gr_ratings=40, gr_reviews=18),
                entry("2026-06-08 15:00:00", 101, 4800, 19, gr_ratings=41, gr_reviews=18),
                entry("2026-06-09 03:00:00", 103, 4600, 17, gr_ratings=43, gr_reviews=19),
                entry("2026-06-10 03:00:00", 105, 4400, 15),  # WAF: no Goodreads
            ],
        }

    @staticmethod
    def _container(dom, marker):
        # Return the slice of DOM from a container's id= attribute up to the
        # next id= attribute, so assertions don't bleed into sibling sections.
        i = dom.find(f'id="{marker}"')
        if i == -1:
            return None
        nxt = dom.find('id="', i + 1)
        return dom[i:nxt] if nxt != -1 else dom[i:i + 1000]

    def test_dashboard_renders_without_js_errors(self):
        chrome = self._find_chrome()
        if not chrome:
            self.skipTest("no Chrome/Chromium binary found")

        import json
        import re
        import subprocess
        import tempfile
        from pathlib import Path

        template = Path(amazon.TEMPLATE_FILE).read_text()
        # Replace the Chart.js CDN script with a no-op stub: the page only ever
        # calls `new Chart(...)`, so this keeps the test offline and fast while
        # still executing every line of the page's own JavaScript.
        template = re.sub(
            r'<script src="https://cdn\.jsdelivr\.net/npm/chart\.js[^"]*"></script>',
            "<script>window.Chart=function(){return{destroy:function(){},"
            "update:function(){}};};</script>",
            template,
        )
        self.assertIn("window.Chart=function", template,
                      "Chart.js CDN stub substitution failed — check the script tag")
        html = template.replace("{{DATA_PLACEHOLDER}}",
                                json.dumps(self._synthetic_envelope()))

        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "index.html"
            page.write_text(html)
            proc = subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                 "--disable-dev-shm-usage", "--dump-dom",
                 "--enable-logging=stderr", "--v=0",
                 "--virtual-time-budget=8000", page.as_uri()],
                capture_output=True, text=True, timeout=60,
            )
        dom, logs = proc.stdout, proc.stderr

        self.assertNotIn("Uncaught", logs,
                         msg=f"JavaScript error during render:\n{logs}")

        # Each metric section is populated by JS after load; empty means the
        # render threw before reaching it.
        for marker, label in (("amazonStats", "Amazon reviews"),
                              ("goodreadsStats", "Goodreads"),
                              ("rankingStats", "current rankings"),
                              ("bestRankingStats", "best rankings")):
            container = self._container(dom, marker)
            self.assertIsNotNone(container, f"{marker} container missing from DOM")
            self.assertIn("stat-value", container,
                          f"{label} stats did not populate (createCharts likely threw)")

        # Latest entry lacks Goodreads, so the GR stats must fall back to the
        # last good fetch (ratings 43 / reviews 19), not vanish or show 0.
        gr = self._container(dom, "goodreadsStats")
        self.assertIn("43", gr, "Goodreads ratings fallback not applied")
        self.assertIn("19", gr, "Goodreads reviews fallback not applied")


class TestLoadBooksValidation(unittest.TestCase):
    """Validation is important because books.json is user-edited; a typo
    should fail loudly, not silently create an orphaned dashboard."""

    def _write_and_load(self, books):
        import json
        from pathlib import Path
        path = Path(amazon.BOOKS_FILE)
        original = path.read_text()
        try:
            path.write_text(json.dumps({"books": books}))
            return amazon.load_books()
        finally:
            path.write_text(original)

    def test_valid_book_loads(self):
        books = self._write_and_load([
            {"slug": "a", "display_name": "A", "amazon_url": "https://x"},
        ])
        self.assertEqual(len(books), 1)

    def test_empty_books_list_rejected(self):
        with self.assertRaises(SystemExit):
            self._write_and_load([])

    def test_invalid_slug_rejected(self):
        with self.assertRaises(SystemExit):
            self._write_and_load([
                {"slug": "BAD_SLUG", "display_name": "x", "amazon_url": "y"},
            ])

    def test_duplicate_slug_rejected(self):
        with self.assertRaises(SystemExit):
            self._write_and_load([
                {"slug": "a", "display_name": "x", "amazon_url": "y"},
                {"slug": "a", "display_name": "z", "amazon_url": "w"},
            ])

    def test_missing_required_field_rejected(self):
        with self.assertRaises(SystemExit):
            self._write_and_load([
                {"slug": "a", "amazon_url": "y"},  # no display_name
            ])


if __name__ == "__main__":
    unittest.main()
