---
date: 2026-04-24
status: brainstorm
topic: amazon-ranking-tool-review
---

# Amazon Ranking Tool — Review & Improvements

## Context

The Amazon ranking tracker has been running in production via cron every 15 minutes since 2025-06-02. Production data (327 days, 30,732 entries, 16 MB JSON on `45.55.137.82:/var/www/amazon_ranking`) reveals several quality issues worth addressing in one coordinated pass. The user flagged one visible symptom (sub-zero y-axis on charts), and review surfaced broader wins in data quality, scraper reliability, simplification, and scope.

## What We're Building

A reliability-and-polish pass on the existing tool, plus a scope expansion to track multiple books.

### 1. Chart correctness

- **Books overall ranking chart**: log scale, reversed y-axis (so up = better; log handles the 4K–140K range readably).
- **Sub-category ranking charts** (Japan Travel Guides, Memoirs, Photo Essays, etc.): linear scale, reversed y-axis, min = 1. These have small ranges (max 69, 33, 2609) where linear reads fine; reversing fixes the "down = better" cognitive mismatch.
- Remove `grace: '10%'` from ranking charts (the cause of the sub-zero artifact).
- Add a **7-day moving average overlay** on every line chart (thin raw + bold smoothed line).
- Add a **combined all-categories chart** per book — all sub-categories on a shared reversed axis.

### 2. Data cleanup (one-time migration)

- Rewrite `data/amazon_history.json` in place with a timestamped backup + dry-run preview (matching the existing `clean_goodreads_data.py` pattern).
- **Schema normalization**: migrate the 107 old `review_count` entries to `amazon_review_count`; leave `goodreads_*` absent where historically absent (don't fabricate).
- **Dedupe**: collapse runs of consecutive-identical entries (86% of rows). Keep the first of each run — retains the moment a change was observed.
- **Drop** the 93 entries with empty rankings (silent scrape failures, no value).

### 3. Scraper reliability

- Switch to a **write-on-change** model: keep the 15-min cron, but only append an entry if the signature (review counts + rankings) differs from the previous entry. Log successful-no-change as a distinct heartbeat.
- **Modern User-Agent string** (current one is Chrome 91 from 2021).
- **Retry with backoff** on transient fetch failures.
- **Failure logging**: append scrape failures (and empty-ranking results) to a log file.
- **Dashboard "last successful scrape" badge** so silent breakage is visible when you open the page.

### 4. Multi-book support

- New `books.json` config at the repo root with entries like `{slug, amazon_url, goodreads_url, display_name}`.
- **One JSON history file per book** under `data/` (e.g., `data/japan-book.json`, `data/<slug>.json`).
- **One dashboard page per book** generated via the existing `dashboard_template.html` indirection (unchanged). A small top-level `index.html` lists all tracked books.
- Scraper iterates the book list per cron run.

### 5. Simplification

- **Drop the CSV dual-write** (`amazon_detailed_history.csv`). No evidence of consumption; removes a second schema that already drifted once. JSON is the source of truth.
- Remove dead code: unused `selectors` list in `get_amazon_review_count()`; the single-element `rank_patterns` list.
- Keep `dashboard_template.html` + `{{DATA_PLACEHOLDER}}` indirection as-is — working and not earning a rewrite.

## Why This Approach

- **Write-on-change over slowing the cron**: preserves the 15-min resolution for capturing genuine moves (Amazon BSR can jump between scrapes), while eliminating 86% redundant bulk. Heartbeat log still proves the scraper is alive when the file is quiet.
- **Log scale only for Books**: the other categories have tight ranges where log would obscure meaningful small changes. Avoid one-size-fits-all.
- **Per-book JSON files** (not a single combined file): matches the "one page per book" dashboard shape, keeps each book's history independently readable, avoids a 50 MB file if the list grows.
- **books.json over a Python constant**: adding a book should not require editing code or a Git commit round-trip. JSON is the lowest-friction format that's still version-controllable.
- **Dry-run migration**: 30K rows on production data is worth inspecting before committing. Matches the project's existing pattern.
- **No new dashboard framework**: the Chart.js + template approach works. Changes are additive (reverse axes, log, moving averages), not a rewrite.

## Key Decisions

| Decision | Choice |
|---|---|
| Books chart axis | Log scale, reversed, min clamped |
| Sub-category chart axis | Linear, reversed, min = 1 |
| Grace / sub-zero fix | Remove `grace: '10%'`, set explicit `min` |
| Write cadence | Write-on-change (cron stays at 15 min) |
| Historical cleanup safety | Timestamped backup + dry-run preview |
| Dead-key schema migration | Normalize `review_count` → `amazon_review_count` |
| CSV output | Dropped |
| Dashboard template indirection | Kept as-is |
| New charts | 7-day moving average overlay + combined all-categories per book |
| Failure alerting | Log file + "last successful scrape" dashboard badge |
| Multi-book scope | Yes — open-ended list |
| Multi-book config | `books.json` in repo root |
| Multi-book data layout | One JSON per book in `data/` |
| Multi-book dashboard | One page per book + top-level index |

## Resolved Questions

1. **Initial books to onboard**: User has specific books in mind and will provide the list at planning time. Build the multi-book infrastructure first; seed `books.json` with the existing Japan book, leave room for additions.

2. **Per-book slug**: Human-readable slug declared per entry in `books.json` (e.g., `japan-book`). Used for both data filename (`data/japan-book.json`) and dashboard URL (`/amazon/japan-book/`). No ASIN indirection.

## Non-Goals (Explicit)

- No alerting via email/webhook this round (dashboard badge is enough).
- No backfill of the 93 dropped empty-rank entries from source (data is gone; moving on).
- No change to `dashboard_template.html`'s data-embedding strategy.
- No retry-by-parsing-cached-HTML — only fetch-level retries.
- No interactive date range selector, no per-book comparison charts this pass.
