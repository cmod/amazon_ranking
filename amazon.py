#!/usr/bin/env python3
"""
amazon.py — scrape Amazon (and optionally Goodreads) for one or more books
configured in books.json, append changed entries to per-book history files,
log every attempt, and render per-book dashboards plus a top-level index.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BOOKS_FILE = ROOT / "books.json"
DATA_DIR = ROOT / "data"
LOG_FILE = DATA_DIR / "scrape_log.jsonl"
TEMPLATE_FILE = ROOT / "dashboard_template.html"

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
INTER_BOOK_DELAY = 2.0       # seconds between books to avoid bot-detection bursts
FETCH_ATTEMPTS = 2
FETCH_BACKOFF = 2.0          # base for exponential backoff: 2s, 4s

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ---------- Logging ----------

class JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            **getattr(record, "extra_fields", {}),
        }
        return json.dumps(payload, ensure_ascii=False)


def get_logger() -> logging.Logger:
    log = logging.getLogger("scrape")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    DATA_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(JsonlFormatter())
    log.addHandler(handler)
    return log


# ---------- Books config ----------

def load_books() -> list[dict]:
    if not BOOKS_FILE.exists():
        raise SystemExit(f"error: {BOOKS_FILE} not found")
    config = json.loads(BOOKS_FILE.read_text())
    books = config.get("books", [])
    if not books:
        raise SystemExit(f"error: {BOOKS_FILE} has no books")
    seen_slugs = set()
    for b in books:
        slug = b.get("slug", "")
        if not SLUG_RE.match(slug):
            raise SystemExit(f"error: invalid slug {slug!r} (must match {SLUG_RE.pattern})")
        if slug in seen_slugs:
            raise SystemExit(f"error: duplicate slug {slug!r}")
        seen_slugs.add(slug)
        if not b.get("amazon_url"):
            raise SystemExit(f"error: book {slug!r} missing amazon_url")
        if not b.get("display_name"):
            raise SystemExit(f"error: book {slug!r} missing display_name")
    return books


# ---------- HTTP ----------

def fetch_with_retry(url: str):
    for i in range(FETCH_ATTEMPTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None  # permanent
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == FETCH_ATTEMPTS - 1:
                return None
            time.sleep(FETCH_BACKOFF * (2 ** i))
    return None


# ---------- Page scraping ----------

def get_amazon_data(url: str) -> dict | None:
    response = fetch_with_retry(url)
    if response is None:
        return None
    soup = BeautifulSoup(response.content, "html.parser")
    return {
        "amazon_review_count": get_amazon_review_count(soup),
        "rankings": get_all_rankings(soup),
    }


def get_goodreads_data(url: str) -> dict | None:
    response = fetch_with_retry(url)
    if response is None:
        return None
    soup = BeautifulSoup(response.content, "html.parser")
    return {
        "goodreads_ratings_count": get_goodreads_ratings_count(soup),
        "goodreads_reviews_count": get_goodreads_reviews_count(soup),
    }


def get_amazon_review_count(soup):
    try:
        review_patterns = [
            r'(\d{1,3}(?:,\d{3})*)\s*(?:customer\s*)?reviews?',
            r'(\d{1,3}(?:,\d{3})*)\s*ratings?',
            r'(\d{1,3}(?:,\d{3})*)\s*global\s*ratings?'
        ]

        for pattern in review_patterns:
            # Look in data-hook-tagged elements first (Amazon uses these)
            for element in soup.find_all(attrs={'data-hook': True}):
                if any(keyword in element.get('data-hook', '').lower()
                       for keyword in ['reviews', 'rating', 'total']):
                    match = re.search(pattern, element.get_text(), re.IGNORECASE)
                    if match:
                        return match.group(1).replace(',', '')

            # Fall back to full-page text
            for match in re.findall(pattern, soup.get_text(), re.IGNORECASE):
                num = int(match.replace(',', ''))
                if 1 <= num <= 1000000:
                    return str(num)
        return None
    except Exception as e:
        print(f"Error extracting Amazon review count: {e}", file=sys.stderr)
        return None


def get_goodreads_ratings_count(soup):
    try:
        span = soup.find('span', {'data-testid': 'ratingsCount'})
        if span:
            match = re.search(r'([\d,]+)', span.get_text())
            if match:
                return str(int(match.group(1).replace(',', '')))
        return None
    except Exception as e:
        print(f"Error extracting Goodreads ratings count: {e}", file=sys.stderr)
        return None


def get_goodreads_reviews_count(soup):
    try:
        span = soup.find('span', {'data-testid': 'reviewsCount'})
        if span:
            match = re.search(r'([\d,]+)', span.get_text())
            if match:
                return str(int(match.group(1).replace(',', '')))
        return None
    except Exception as e:
        print(f"Error extracting Goodreads reviews count: {e}", file=sys.stderr)
        return None


def get_all_rankings(soup):
    rankings = []
    try:
        rank_section = soup.find(string=lambda t: t and "Best Sellers Rank" in t)
        if not rank_section:
            return rankings

        rank_container = rank_section.parent
        for _ in range(5):
            if rank_container is None or rank_container.find_all(['li', 'span']):
                break
            rank_container = rank_container.parent
        if rank_container is None:
            return rankings

        rank_text = rank_container.get_text()
        rank_pattern = r'#([\d,]+)\s+in\s+([^#\n]+?)(?=\s*(?:#|\s*$))'

        for rank_num, category in re.findall(rank_pattern, rank_text, re.MULTILINE | re.IGNORECASE):
            cleaned_category = re.sub(r'\s*\([^)]*\)\s*$', '', category.strip()).strip()
            if cleaned_category and rank_num and len(cleaned_category) < 100:
                rankings.append({
                    'rank': rank_num.replace(',', ''),
                    'category': cleaned_category
                })

        # Dedupe by category while preserving order
        seen = set()
        return [r for r in rankings if not (r['category'] in seen or seen.add(r['category']))]
    except Exception as e:
        print(f"Error extracting rankings: {e}", file=sys.stderr)
        return rankings


# ---------- Signatures & persistence ----------

def _norm_count(v):
    if v in (None, "", "0", 0):
        return None
    return int(v) if isinstance(v, str) else v


def entry_signature(entry: dict, has_goodreads: bool) -> tuple:
    # Sort rankings by category (not rank) — categories are the stable identifier;
    # sorting by rank causes false "no change" signatures when ranks cross.
    rankings = tuple(sorted(
        (r["category"], int(r["rank"]))
        for r in entry.get("rankings", [])
    ))
    base = (_norm_count(entry.get("amazon_review_count")), rankings)
    if has_goodreads:
        base = base + (
            _norm_count(entry.get("goodreads_ratings_count")),
            _norm_count(entry.get("goodreads_reviews_count")),
        )
    return base


def load_envelope(slug: str, display_name: str) -> dict:
    path = DATA_DIR / f"{slug}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "entries" in data:
                data["slug"] = slug
                data["display_name"] = display_name  # books.json is source of truth
                data.setdefault("last_successful_scrape", None)
                data.setdefault("last_error", None)
                data.setdefault("last_attempt_timestamp", None)
                data.setdefault("last_attempt_status", None)
                return data
        except json.JSONDecodeError:
            pass
    return {
        "slug": slug,
        "display_name": display_name,
        "last_successful_scrape": None,
        "last_error": None,
        "last_attempt_timestamp": None,
        "last_attempt_status": None,
        "entries": [],
    }


def write_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        delete=False, encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


# ---------- Per-book scrape ----------

def scrape_book(book: dict, log: logging.Logger) -> None:
    slug = book["slug"]
    display_name = book["display_name"]
    has_goodreads = bool(book.get("goodreads_url"))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    envelope = load_envelope(slug, display_name)
    envelope["last_attempt_timestamp"] = now

    data_path = DATA_DIR / f"{slug}.json"

    amazon_data = get_amazon_data(book["amazon_url"])
    if amazon_data is None or not amazon_data.get("rankings"):
        envelope["last_attempt_status"] = "failed"
        envelope["last_error"] = "Amazon fetch failed or returned no rankings"
        write_atomic(data_path, envelope)
        log.info("scrape", extra={"extra_fields": {
            "slug": slug, "status": "failed", "reason": "amazon-fetch",
        }})
        print(f"[{slug}] failed: Amazon fetch")
        return

    arc = amazon_data.get("amazon_review_count")
    if arc is None or arc in ("0", 0):
        envelope["last_attempt_status"] = "failed"
        envelope["last_error"] = f"Invalid amazon_review_count: {arc!r}"
        write_atomic(data_path, envelope)
        log.info("scrape", extra={"extra_fields": {
            "slug": slug, "status": "failed", "reason": "invalid-review-count",
        }})
        print(f"[{slug}] failed: invalid review count ({arc!r})")
        return

    new_entry = {
        "timestamp": now,
        "amazon_review_count": arc,
        "rankings": amazon_data.get("rankings"),
    }

    if has_goodreads:
        gr_data = get_goodreads_data(book["goodreads_url"])
        if gr_data:
            # Only include fields if both are present; None-mixed entries pollute signatures.
            ratings = gr_data.get("goodreads_ratings_count")
            reviews = gr_data.get("goodreads_reviews_count")
            if ratings is not None:
                new_entry["goodreads_ratings_count"] = ratings
            if reviews is not None:
                new_entry["goodreads_reviews_count"] = reviews
        # Goodreads fetch failure is not a scrape-level failure — omit and move on.

    entries = envelope["entries"]
    new_sig = entry_signature(new_entry, has_goodreads)
    wrote_entry = False
    if not entries or entry_signature(entries[-1], has_goodreads) != new_sig:
        entries.append(new_entry)
        wrote_entry = True

    envelope["last_successful_scrape"] = now
    envelope["last_error"] = None
    envelope["last_attempt_status"] = "appended" if wrote_entry else "no-change"
    envelope["entries"] = entries

    write_atomic(data_path, envelope)

    log.info("scrape", extra={"extra_fields": {
        "slug": slug, "status": "success", "wrote_entry": wrote_entry,
        "reason": "appended" if wrote_entry else "no-change",
    }})

    gr_status = "no"
    if has_goodreads and "goodreads_ratings_count" in new_entry:
        gr_status = "yes"
    print(f"[{slug}] {'appended' if wrote_entry else 'no-change'}: "
          f"reviews={arc} rankings={len(new_entry['rankings'])} goodreads={gr_status}")


# ---------- Dashboard generation ----------

def generate_book_dashboard(book: dict, output_dir: Path) -> bool:
    slug = book["slug"]
    data_path = DATA_DIR / f"{slug}.json"
    if not data_path.exists():
        return False
    template = TEMPLATE_FILE.read_text()
    html = template.replace("{{DATA_PLACEHOLDER}}", data_path.read_text())
    dest = output_dir / slug / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html)
    return True


def generate_top_index(books: list[dict], output_dir: Path) -> None:
    rows = []
    for b in books:
        slug = b["slug"]
        name = b["display_name"]
        if (DATA_DIR / f"{slug}.json").exists():
            rows.append(f'      <li><a href="{slug}/">{name}</a></li>')
        else:
            rows.append(f'      <li>{name} <em>(pending first scrape)</em></li>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Book Tracking</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           max-width: 600px; margin: 4rem auto; padding: 0 1rem; color: #222; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 1rem; }}
    ul {{ line-height: 1.8; padding-left: 1.25rem; }}
    a {{ color: #0366d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    em {{ color: #999; font-style: italic; }}
  </style>
</head>
<body>
  <h1>Tracked Books</h1>
  <ul>
{chr(10).join(rows)}
  </ul>
</body>
</html>
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html)


# ---------- Main ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="Amazon Book Ranking Tracker")
    parser.add_argument("--output-dir", "-o", default=".",
                        help="Output directory for dashboards (default: current directory)")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Skip scraping; regenerate dashboards from existing data only")
    args = parser.parse_args()

    log = get_logger()
    books = load_books()
    output_dir = Path(args.output_dir).resolve()

    if not args.skip_scrape:
        for i, book in enumerate(books):
            try:
                scrape_book(book, log)
            except Exception as e:
                log.exception("scrape crash", extra={"extra_fields": {"slug": book["slug"]}})
                print(f"[{book['slug']}] crash: {e}", file=sys.stderr)
            if i < len(books) - 1:
                time.sleep(INTER_BOOK_DELAY)

    for book in books:
        if generate_book_dashboard(book, output_dir):
            print(f"[{book['slug']}] dashboard: {output_dir}/{book['slug']}/index.html")

    generate_top_index(books, output_dir)
    print(f"Top-level index: {output_dir}/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
