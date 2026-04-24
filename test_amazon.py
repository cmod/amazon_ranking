"""
Regression tests for amazon.py's HTML extraction + signature logic.

Run:
    ./venv/bin/python -m unittest test_amazon.py
    # or
    ./venv/bin/python test_amazon.py
"""
from __future__ import annotations

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
