---
title: Amazon Ranking Tool — Multi-Book Support, Chart Fixes, and Data Cleanup
type: feat
status: active
date: 2026-04-24
deepened: 2026-04-24
---

# Amazon Ranking Tool — Multi-Book Support, Chart Fixes, and Data Cleanup

Source: [`docs/brainstorms/2026-04-24-amazon-ranking-tool-review-brainstorm.md`](../brainstorms/2026-04-24-amazon-ranking-tool-review-brainstorm.md)

## Enhancement Summary

Deepened 2026-04-24 with six parallel review/research agents (Python code quality, migration safety, simplicity, spec-flow, performance, external research on Chart.js + requests retry + JSONL rotation).

**Key improvements folded in:**

1. **Migration strategy pivot** — instead of in-place rewrite of `data/amazon_history.json` + later rename, Phase 3 writes cleaned output *directly* to `data/japan-book.json` with the Phase-5 envelope already in place. Eliminates cron race, collapses Phase 3↔4 coordination, and leaves the original file untouched as a natural backup.
2. **Data envelope defined once, in Phase 4** — `{slug, display_name, last_successful_scrape, last_error, entries}`. Phases 3, 5, 6 all read/write the same shape (was previously inconsistent between phases).
3. **Signature correctness** — sort rankings by `category` (not `rank`, which can cause false dedupes when ranks cross between entries); normalize counts to `int | None` before tupling (historical data has mixed str/int/None).
4. **Atomic writes everywhere** — `tempfile + os.replace` for every JSON write (migration + per-scrape append). Single biggest reliability win.
5. **Per-book failure isolation** — explicit `try/except` per book in the scrape loop; one failing book can't kill the rest.
6. **90% drop guard replaced** — now an absolute range check `[3500, 6000]` based on the profile (more meaningful than a percentage that barely exceeds the expected 86% drop).
7. **JSONL log uses `logging.handlers.RotatingFileHandler`** — research confirmed it works fine for short-lived cron scripts (the known rotation bug is with `TimedRotatingFileHandler`, not size-based). Stdlib, no new deps.
8. **Chart.js pin to `@4.4.0`** is now a Phase-1 acceptance criterion; `animation: false` + `parsing: false` + pre-shaped `{x, y}` data for snappier rendering.
9. **Clarified log-vs-linear rule** — log scale where a series' range spans >2 orders of magnitude (`Books`, combined-sub-categories). Linear where it doesn't (individual sub-categories).
10. **Simplifications** — merged Phase 1+2 into a single "quick wins" deploy; fixed 2s inter-book sleep (was `random.uniform(1,3)`); moving-average scoped to charts where noise actually obscures signal.

**New gaps filled:** book removal / slug rename policy documented; empty `books.json` handling; never-scraped book state on dashboard; MA behavior with <7 days data; Goodreads-present-vs-absent effect on signature.

**Non-issues confirmed:** dashboard load time at projected data volumes is fine; moving-average O(n·w) is fine; sequential scraping is correct by design (don't parallelize — defeats anti-detection jitter).

## Overview

Coordinated improvement pass on the year-old Amazon book-ranking tracker. Fixes the sub-zero y-axis bug, strips cruft (CSV dual-write, dead code), hardens the scraper (write-on-change, retries, modern User-Agent, failure logging, "last scrape" dashboard badge), cleans 86% consecutive-duplicate rows from 11 months of production data with a safe dry-run-first migration that *writes a new file alongside* the original, and introduces multi-book tracking via a `books.json` config with one dashboard page per book.

## Problem Statement

Production data on `45.55.137.82:/var/www/amazon_ranking` (30,732 entries across 327 days) shows:

- **Chart correctness**: `grace: '10%'` extends ranking axes below zero (ranks can't be <1); direction is counterintuitive (lower = better, line descends when doing *better*); `Books` rank spans 4K–140K and is illegible on linear.
- **Data quality**: 86% consecutive duplicates; 107 legacy `review_count` entries; 93 empty-ranking entries from silent scrape failures.
- **Scraper fragility**: Chrome 91 User-Agent (2021); no retries; no failure logging; no breakage visibility.
- **Scope**: hardcoded single book; user wants open-ended multi-book support.
- **Cruft**: unused CSV dual-write; dead `selectors` and single-element `rank_patterns` lists.

## Proposed Solution

Six phases. Phase 1+2 ship together as "quick wins." Phase 3 is the one-shot migration. Phases 4–6 are the structural work and its enrichment.

| Phase | Scope | Risk | Rollback |
|---|---|---|---|
| 1+2. Quick wins (charts + cruft) | `dashboard_template.html`, `amazon.py` dead code, CSV dropped | None — pure frontend + mechanical deletions | `git revert` |
| 3. Historical migration | New `migrate_history.py`; writes cleaned output to new file | Low — original file untouched | Delete new file, done |
| 4. Multi-book refactor | `books.json`, per-book data envelope, per-book pages | Medium — restructures file layout + cron deploy sync | Documented deploy sequence |
| 5. Reliability | Write-on-change signatures, retries, UA, failure log | Low — additive | `git revert` |
| 6. Dashboard enrichment | MA on select charts, combined chart, "last scrape" badge | None — frontend + template | `git revert` |

## Phase 1+2 — Chart Fixes and Cruft Removal (shipped together)

**Files:** `dashboard_template.html`, `amazon.py`, `README.md`

### Chart axis fixes

Per-category ranking charts get per-dataset branching: `Books` uses log+reversed (its 4K–140K range demands it), other categories use linear+reversed with `min: 1`. Grace removed; title copy updated to "Ranking (higher on chart = better)". Amazon Reviews and Goodreads charts get `beginAtZero: true`, keeping `grace` only with that floor.

**Recommended shape (per `dashboard_template.html:281` area):**

```js
// Log scale only when range spans >2 orders of magnitude
const isWideRange = dataset.label === 'Books';
scales: {
  y: {
    type: isWideRange ? 'logarithmic' : 'linear',
    reverse: true,
    min: 1,
    title: { display: true, text: 'Ranking (higher on chart = better)' },
    ticks: { format: { notation: 'compact' } }  // "10K" vs "10000"
    // no `grace`
  }
}
```

### Chart.js pin + perf hints

- Pin CDN to `@4.4.0`: `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0">`.
- Add `animation: false` to initial render config (animating thousands of points is the real jank source).
- Add `parsing: false` and shape all datasets as `[{x, y}, ...]` objects up-front.
- `pointRadius: 0` on raw-data series (currently set in per-category, extend to combined chart in Phase 6).

### Cruft removal

- Delete `save_book_data()` (`amazon.py:270-310`) and its call (`amazon.py:379`).
- Remove `import csv` (`amazon.py:4`).
- Delete unused `selectors` list (`amazon.py:96-104`).
- Collapse `rank_patterns` list (`amazon.py:197-203`) to a single regex string.
- `README.md`: drop CSV mentions from File Structure, Data Outputs, Features.
- Keep existing `data/amazon_detailed_history.csv` on disk (historical artifact); just stop writing.

### Research insights

**Chart.js log+reverse combination** (Chart.js 4.x): works correctly; `reverse: true` is a common scale option supported uniformly including for `type: 'logarithmic'`. The zero-value silent-drop gotcha ([issue #9629](https://github.com/chartjs/Chart.js/issues/9629)) is not relevant for ranks (always ≥1). PR #5076 fixed an older double-reverse quirk years ago.

### Acceptance criteria

- [x] No chart y-axis shows negative values; confirmed in browser across all categories.
- [x] `Books` chart renders log-scaled; ranks readable at both 4K and 140K.
- [x] Sub-category charts render "up = better".
- [x] Chart.js version pinned to `@4.4.0` in the template.
- [x] `python amazon.py` runs with no CSV writes.
- [x] `grep -r "csv\|CSV\|detailed_history" amazon.py` returns no hits.
- [x] README accurately describes current (CSV-free) state.

## Phase 3 — One-Time Historical Migration (write-next-to-original)

**New file:** `migrate_history.py` (one-shot; not called by cron).

**Key strategy change from initial plan**: instead of rewriting `amazon_history.json` in place, output goes *directly* to `data/japan-book.json` with the Phase-4 envelope already applied. The original file is not touched. This:

- Eliminates the cron race entirely (cron keeps writing to the old file; we ignore those writes).
- Makes rollback trivial (`rm data/japan-book.json`).
- Collapses the Phase 3→4 coordination: no separate "rename" step later.
- Leaves the pre-migration raw data on disk as a natural backup.

### Migration rules

- **Schema normalize**: `review_count` → `amazon_review_count` (107 entries).
- **Dedupe**: signature = `(amazon_review_count, goodreads_ratings_count, goodreads_reviews_count, rankings_tuple)` where `rankings_tuple = tuple(sorted((category, int(rank)) for r in rankings))`. **Sort by category, not rank** — two categories can share a rank, and sort-by-rank-first produces order-flips that create false "no-change" signatures.
- **Drop empty**: entries with no `rankings` or `rankings == []` removed.
- **Wrap in envelope** (Phase-4 shape):

```json
{
  "slug": "japan-book",
  "display_name": "Things Become Other Things",
  "last_successful_scrape": "<last-entry-timestamp>",
  "last_error": null,
  "entries": [ ... cleaned entries ... ]
}
```

### Safety

- **Sanity range** (replaces the prior 90%-drop guard): refuse to commit if `len(cleaned_entries)` is outside `[3500, 6000]`. This is a principled bound derived from the data profile, not a percentage that barely exceeds the expected drop.
- **Atomic write**: temp file in the same directory + `os.replace` — never a partially-written target.
- **Mtime check**: record `input_mtime` at load; abort if it changes before write (defense in depth — shouldn't happen since we're writing to a different file).
- **Input hash recorded**: write `data/migration_report.json` with `{input_path, input_sha256, input_entry_count, output_entry_count, dropped_empty, normalized_schema, timestamp}` for post-hoc auditability.

### CLI

```bash
# Dry-run (default) — prints summary, samples, and would-be counts
python migrate_history.py

# Commit: writes data/japan-book.json + data/migration_report.json
python migrate_history.py --commit

# Custom paths (rare)
python migrate_history.py --input data/amazon_history.json \
                         --output data/japan-book.json \
                         --slug japan-book \
                         --display-name "Things Become Other Things" \
                         --commit
```

### Post-migration invariants (verified by script, printed on commit)

- [ ] `len(entries)` within `[3500, 6000]`.
- [ ] No entry has a `review_count` key; every entry has `amazon_review_count`.
- [ ] No entry has `rankings == []`.
- [ ] `entries[i].timestamp <= entries[i+1].timestamp` for all i (monotonicity).
- [ ] Each category present in the source appears at least once in output (no category vanished entirely).
- [ ] `entries[0].timestamp` matches first surviving source entry after empty-ranking drops; `entries[-1].timestamp` matches last.

### Acceptance criteria

- [ ] Dry-run prints counts, 5-line samples of each transformation, and the envelope preview.
- [ ] `--commit` writes `data/japan-book.json` atomically + `data/migration_report.json`.
- [ ] Script refuses if output count is outside `[3500, 6000]`.
- [ ] Running twice is idempotent — the second run either detects an existing wrapped output and refuses, or produces identical bytes.
- [ ] Every entry in output has `amazon_review_count`; none has `review_count`; none has empty `rankings`.
- [ ] Source file `data/amazon_history.json` is unchanged after `--commit`.

**Deploy note:** run on the server where the authoritative 16 MB JSON lives. The SCP snapshot I pulled locally was only for profiling.

## Phase 4 — Multi-Book Refactor

**New file:** `books.json` at repo root.

```json
{
  "books": [
    {
      "slug": "japan-book",
      "display_name": "Things Become Other Things",
      "amazon_url": "https://www.amazon.com/dp/0593732545",
      "goodreads_url": "https://www.goodreads.com/book/show/217245583"
    }
  ]
}
```

- `slug`: required, matches `^[a-z0-9-]+$`, immutable once assigned (renaming orphans the data file and dashboard URL).
- `display_name`: required, rendered in page title and top-level index.
- `amazon_url`: required.
- `goodreads_url`: optional — if absent, skip Goodreads fetch silently (don't treat as failure).

### Per-book data envelope (canonical shape, shared with Phase 3 and 5)

```json
{
  "slug": "japan-book",
  "display_name": "Things Become Other Things",
  "last_successful_scrape": "2026-04-24T15:30:00",
  "last_error": null,
  "last_attempt_timestamp": "2026-04-24T15:30:00",
  "last_attempt_status": "no-change",
  "entries": [ { "timestamp": "...", "amazon_review_count": "...", "rankings": [...] }, ... ]
}
```

### `amazon.py` refactor

- Module-level constant: `BOOKS = json.loads(Path("books.json").read_text())["books"]` (inline — don't wrap three lines of I/O in a `load_books()` function).
- Validate books on startup: assert `slug` regex, assert uniqueness, assert `amazon_url` present. Abort with logged error if any book is malformed.
- `main()` iterates `BOOKS`:

```python
for i, book in enumerate(BOOKS):
    try:
        scrape_book(book)  # fetch, compare, write-on-change, update status fields
    except Exception:
        scrape_log.exception("scrape failed", extra={"extra_fields": {"slug": book["slug"]}})
        # other books continue
    if i < len(BOOKS) - 1:
        time.sleep(2.0)  # fixed; jitter is theater at 1-2 books
```

- `save_book_data_json(book, new_entry)` takes the book dict; writes to `data/{slug}.json`; uses atomic `tempfile + os.replace`.
- `generate_book_dashboard(book, output_dir)` renders the existing template into `{output_dir}/{slug}/index.html`.
- `generate_top_index(books_with_data, output_dir)` runs **once after the loop**, writing `{output_dir}/index.html` listing only books whose `data/{slug}.json` exists (others show as "pending first scrape" placeholder).

### Book-lifecycle policy (documented in README)

- **Adding a book**: edit `books.json`, next cron scrape creates `data/{slug}.json` and `{output_dir}/{slug}/index.html`.
- **Removing a book**: edit `books.json`. Orphan `data/{slug}.json` and dashboard page are left on disk (not auto-deleted — avoid accidental data loss). They stop appearing in the top-level index immediately.
- **Renaming a slug**: don't. If you must, rename `data/{slug}.json` by hand *before* the next cron fires.
- **Two books with same `amazon_url`**: allowed (e.g., tracking the same book as two ASINs); slug uniqueness is the only constraint.

### Deploy sequence (server)

```bash
set -euo pipefail

# 1. Verify no scrape in flight, then disable cron
pgrep -f "python amazon.py" && { echo "scrape running, wait"; exit 1; }
crontab -l > /tmp/cron.bak
crontab -r

# 2. Pull code (books.json, migrate_history.py, new amazon.py, new template)
cd /var/www/amazon_ranking
git pull

# 3. Run migration (writes data/japan-book.json alongside untouched original)
./venv/bin/python migrate_history.py          # dry-run first
./venv/bin/python migrate_history.py --commit

# 4. Run scraper once; confirm it appends to japan-book.json and renders dashboard
./venv/bin/python amazon.py --output-dir /var/www/specialprojects.jp/public_html/amazon

# 5. Verify dashboard pages
ls /var/www/specialprojects.jp/public_html/amazon/japan-book/
ls /var/www/specialprojects.jp/public_html/amazon/index.html

# 6. ONLY after verification, restore cron
crontab /tmp/cron.bak
```

### URL change

- Before: `https://specialprojects.jp/amazon/` → Japan book dashboard.
- After: `https://specialprojects.jp/amazon/` → top-level index; `https://specialprojects.jp/amazon/japan-book/` → Japan book dashboard.

### Acceptance criteria

- [ ] `books.json` with Japan book loads; invalid slug / duplicate slug / missing required field aborts with a clear error.
- [ ] Missing `goodreads_url` doesn't break scrape; book's dashboard omits Goodreads charts gracefully.
- [ ] Per-book exception in the loop does not abort the rest.
- [ ] Each book's data persists to `data/{slug}.json` with the canonical envelope.
- [ ] Top-level index lists books with existing data files; books with no data yet show "pending first scrape" placeholder.
- [ ] Adding a new book to `books.json` requires zero Python code edits.

## Phase 5 — Write-on-Change & Scraper Reliability

**File:** `amazon.py`

### Write-on-change (signature)

```python
def _norm_count(v):
    if v in (None, "", "0", 0):
        return None
    return int(v) if isinstance(v, str) else v

def entry_signature(entry: dict, has_goodreads: bool) -> tuple:
    rankings = tuple(sorted(
        (r["category"], int(r["rank"]))   # sort by category — fixes false-dedupe bug
        for r in entry.get("rankings", [])
    ))
    base = (_norm_count(entry.get("amazon_review_count")), rankings)
    if has_goodreads:
        base = base + (
            _norm_count(entry.get("goodreads_ratings_count")),
            _norm_count(entry.get("goodreads_reviews_count")),
        )
    return base
```

- Per-book logic: load existing envelope, compute signature of new scrape, compare to `entry_signature(envelope["entries"][-1], has_goodreads)`.
- If different: append new entry.
- If same: skip append, still update `last_successful_scrape` and `last_attempt_timestamp` + `last_attempt_status = "no-change"`.
- `has_goodreads` is `goodreads_url in book`. This avoids spurious "changed" signatures when Goodreads is toggled.
- **File is rewritten atomically on every attempt**, regardless of whether a new entry was appended — status fields always reflect the latest scrape.

### Retry with backoff (simplified)

```python
import time, requests

def fetch_with_retry(url: str, *, attempts: int = 2, base: float = 2.0) -> requests.Response | None:
    for i in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == attempts - 1:
                return None
            time.sleep(base * (2 ** i))  # 2s, 4s
```

Two attempts, not three. If both fail, the next cron tick is 15 minutes away and tries again — no need to overengineer single-run retry at cron cadence.

### Modern User-Agent

Replace the Chrome 91 string with a current macOS Chrome (e.g., Chrome 130+). Add `Accept`, `Accept-Language`, `Accept-Encoding`, `Sec-Fetch-Dest`, `Sec-Fetch-Mode`, `Sec-Fetch-Site` matching a real browser.

### Failure logging (stdlib `RotatingFileHandler`)

Research confirmed `RotatingFileHandler` works correctly for short-lived cron scripts (the known rotation-bug is with `TimedRotatingFileHandler`, not the size-based variant — it checks `maxBytes` on every `emit()`).

```python
import logging, json
from logging.handlers import RotatingFileHandler

class JsonlFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            **getattr(record, "extra_fields", {}),
        }
        return json.dumps(payload, ensure_ascii=False)

handler = RotatingFileHandler(
    "data/scrape_log.jsonl",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
handler.setFormatter(JsonlFormatter())
scrape_log = logging.getLogger("scrape")
scrape_log.setLevel(logging.INFO)
scrape_log.addHandler(handler)

# Usage
scrape_log.info("scrape", extra={"extra_fields": {
    "slug": book["slug"], "status": "success", "wrote_entry": False, "reason": "no-change"
}})
```

- Every cron run produces at least one line per book (success/failure/no-change).
- Rotation happens at start-of-line write when size exceeds 10 MB; produces `.1.jsonl` through `.5.jsonl`.

### Per-book status transitions

| Outcome | `last_successful_scrape` | `last_error` | `last_attempt_status` |
|---|---|---|---|
| Success, new entry | updated to now | cleared | `"appended"` |
| Success, no change (heartbeat) | updated to now | cleared | `"no-change"` |
| Failure | unchanged | set to error message | `"failed"` |

Heartbeats count as success for the purposes of `last_successful_scrape` and `last_error` — the scraper reached Amazon and parsed correctly; there was simply nothing new to record.

### Acceptance criteria

- [ ] Two runs with no Amazon change: 0 new entries appended to `data/{slug}.json`.
- [ ] `data/scrape_log.jsonl` gains one line per book per run, regardless of change outcome.
- [ ] Simulated HTTP 503: triggers one retry with 2s backoff, then logs failure.
- [ ] `last_successful_scrape` updates on both change and no-change outcomes.
- [ ] `last_error` populates on failure, clears on next success.
- [ ] User-Agent references a Chrome version released within the last 6 months.
- [ ] Per-book exception inside `scrape_book()` does not abort the outer loop.

## Phase 6 — Dashboard Enrichment

**File:** `dashboard_template.html`

### "Last scrape" badge

- Reads `last_successful_scrape`, `last_error`, `last_attempt_status` from embedded envelope.
- Default: small banner, "Last updated: 2 hours ago" (relative).
- State colors:
  - Green dot: last success < 2h ago.
  - Yellow: 2–6h ago.
  - Red: > 6h ago, badge text prefixed with "⚠".
  - Distinct "pending first scrape" state for never-scraped books (`last_successful_scrape == null`).
- If `last_error != null`: render in a collapsible `<details>` under the badge.

### 7-day moving average (scoped)

Scoped rather than blanket-applied. Apply to charts where short-term noise obscures trend:

- **Apply:** Books overall rank chart (high variance).
- **Apply:** each sub-category rank chart (varies enough to benefit).
- **Skip:** Amazon review count (monotonically increasing; MA adds no value).
- **Skip:** Goodreads ratings / reviews (same; monotonic).
- **Skip:** combined chart (visually noisy with N overlays).

**Implementation:** naive O(n·w) is fine (performance oracle confirmed — ~1.3M ops across affected charts, sub-10ms):

```js
function movingAverage(points, windowDays = 7) {
  const msWindow = windowDays * 24 * 3600 * 1000;
  return points.map((p, i) => {
    const cutoff = p.x.getTime() - msWindow;
    let sum = 0, n = 0;
    for (let j = i; j >= 0 && points[j].x.getTime() >= cutoff; j--) {
      sum += points[j].y; n++;
    }
    return { x: p.x, y: n ? sum / n : null };
  });
}
```

- Style: `borderWidth: 3`, `pointRadius: 0`, no fill.
- With <7 days of data: render partial MA (average of whatever window is available). Skip the MA entirely if fewer than 3 entries exist.

### Combined all-categories chart

- One chart per book titled "All Sub-Categories".
- Excludes `Books` (range would swamp everything).
- Shared y-axis: **log reversed, min=1** (log justified because sub-cat ranges differ up to ~80× — Memoirs max 2609 vs Photo Essays max 33). This doesn't contradict Phase 1's per-category linear rule: log applies when a single chart must accommodate multiple wide ranges.
- Distinct color per category; legend visible; `spanGaps: false` so a category's line breaks where Amazon didn't report that category.
- Hide the chart gracefully if fewer than 2 sub-categories exist for a book.

### Acceptance criteria

- [ ] Badge shows relative time; color transitions at 2h and 6h; "pending first scrape" state for never-scraped books.
- [ ] MA overlay visible on ranking charts only; absent from review/Goodreads charts; renders partial on books with <7 days of data.
- [ ] Combined chart renders with all sub-categories on a shared log-reversed axis; hidden if <2 sub-categories.
- [ ] Mobile layout (<600 px viewport) remains usable.

## Implementation Order & Dependencies

```
Phase 1+2 ──► ships first (no dependencies)
Phase 3 ─────► writes data/japan-book.json with Phase-4 envelope (new file, original untouched)
Phase 4 ─────► depends on Phase 3 (reads envelope it created)
Phase 5 ─────► depends on Phase 4 (envelope shape + per-book structure)
Phase 6 ─────► depends on Phase 5 (reads last_successful_scrape)
```

Recommended commit sequence:
1. Commit Phase 1+2 — push, deploy immediately (visible chart fix + cleanup).
2. Commit Phase 3 script — don't run on prod yet.
3. Commit Phase 4, 5, 6 on the feature branch.
4. On server: execute the Phase 4 deploy sequence (which runs Phase 3's migration as step 3).

## Technical Considerations

- **Pin Chart.js to `@4.4.0`** — log-scale tick generation has had minor bugs across patch releases; specific pin avoids surprise drift.
- **Log scale boundary**: `min: 1` is safe. Chart.js silently drops zero/negative values on log scales ([#9629](https://github.com/chartjs/Chart.js/issues/9629)) — N/A for ranks, but flagged in case future metrics are added.
- **Atomic writes**: every JSON write (migration, per-scrape append) uses `tempfile.NamedTemporaryFile(dir=path.parent) + os.replace(tmp, path)`. Prevents corruption on crash mid-write.
- **JSON file locking**: single-process cron at 15-min cadence on a personal tool — race-condition-free in practice. Not adding `fcntl.flock`.
- **Sequential scraping is correct by design**: 2s sleep between books avoids Amazon bot-detection bursts. Parallelization would defeat it; performance oracle confirmed it's not a perf compromise.
- **Log rotation**: `RotatingFileHandler` is the right tool — research confirmed the known short-lived-script rotation bug is specific to `TimedRotatingFileHandler`, not size-based.
- **Timezone**: timestamps stay naive local time for historical continuity. Not a v1 concern.

## Success Metrics

- Zero negative y-axis labels in rendered charts (the user-reported bug, closed).
- Week 1 post-Phase-5: `data/japan-book.json` grows by ≤ 30 entries (was ~672/week at 15-min cadence with duplicates; write-on-change collapses this to actual BSR changes).
- `data/scrape_log.jsonl` exists, is populated with one line per book per cron run, and rotates when large.
- Adding a second book to `books.json` requires zero Python edits and one cron tick to produce a dashboard.
- `migration_report.json` records the pre/post state with hashes for audit.

## Dependencies & Risks

**Dependencies:** none new. Stdlib (`logging`, `tempfile`, `pathlib`) + existing `requests`, `beautifulsoup4`.

**Risks:**

1. **Migration script bug destroys data** — mitigated by write-next-to-original strategy (original file never modified), dry-run default, absolute-range sanity check, migration report with hash.
2. **Cron race during deploy** — mitigated by explicit `pgrep` check and `crontab -r` before any file ops, and by the fact that the new file path is different from the old.
3. **Amazon HTML changes break rank extraction** — out of scope, but Phase 5's logging + dashboard badge surface it fast.
4. **Signature sort bug producing false dedupes** — fixed by sorting on `category` (not `rank`). Was a real risk in the initial plan.
5. **Count type inconsistency causing spurious "change" signals** — fixed by `_norm_count()` coercion in `entry_signature()`.
6. **Chart.js 4 log+reverse corner cases** — researched; combination is documented and supported. Ranks never reach 0, so the silent-zero gotcha doesn't apply.
7. **Orphaned per-book files after slug rename** — policy documented: slugs are immutable; rename requires manual file move.

## Non-Goals (Explicit)

- No email/webhook alerting this pass (dashboard badge is the alerting surface).
- No backfill of the 93 dropped empty-ranking entries.
- No change to the `{{DATA_PLACEHOLDER}}` template indirection.
- No interactive date-range selector, no cross-book comparison charts.
- No migration away from the Chart.js CDN.
- No automatic cleanup of orphaned per-book files when a book is removed from `books.json`.

## References

- Brainstorm: `docs/brainstorms/2026-04-24-amazon-ranking-tool-review-brainstorm.md`
- Current scraper: `amazon.py:26-48` (Amazon fetch), `amazon.py:167-229` (rank extraction)
- Current chart config: `dashboard_template.html:281-315`
- Prior migration pattern: `clean_goodreads_data.py:19-70`
- Production server: `craigmod@45.55.137.82:/var/www/amazon_ranking`
- Production cron: `*/15 * * * * cd /var/www/amazon_ranking && ./venv/bin/python amazon.py --output-dir /var/www/specialprojects.jp/public_html/amazon`
- Chart.js 4 log axis: https://www.chartjs.org/docs/latest/axes/cartesian/logarithmic.html
- Chart.js zero-drop issue: https://github.com/chartjs/Chart.js/issues/9629
- `RotatingFileHandler` vs `TimedRotatingFileHandler` rotation bug: https://github.com/python/cpython/issues/84649
- urllib3 `Retry` (alternative to manual loop): https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html
