#!/usr/bin/env python3
"""
migrate_history.py — one-shot migration for amazon_history.json.

Reads the legacy single-book history file, normalizes schema
(`review_count` → `amazon_review_count`), collapses consecutive-duplicate
entries, drops empty-ranking entries, and wraps the output in the
multi-book envelope expected by amazon.py after the Phase-4 refactor.

Default behavior is dry-run. Use --commit to actually write the output and
the migration_report.json audit file.

Usage:
  python migrate_history.py                     # dry-run
  python migrate_history.py --commit            # write data/japan-book.json
  python migrate_history.py --input X --output Y --slug Z --display-name "..." --commit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SANITY_MIN = 3500
SANITY_MAX = 6000
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _norm_count(v):
    if v in (None, "", "0", 0):
        return None
    return int(v) if isinstance(v, str) else v


def entry_signature(entry: dict) -> tuple:
    # Sort rankings by category, not rank — two categories can share a rank, and
    # sorting by rank first causes order-flips that produce false "no change"
    # signatures when ranks cross between entries.
    rankings = tuple(sorted(
        (r["category"], int(r["rank"]))
        for r in entry.get("rankings", [])
    ))
    return (
        _norm_count(entry.get("amazon_review_count")),
        _norm_count(entry.get("goodreads_ratings_count")),
        _norm_count(entry.get("goodreads_reviews_count")),
        rankings,
    )


def normalize_entry(entry: dict) -> dict:
    if "review_count" in entry and "amazon_review_count" not in entry:
        e = dict(entry)
        e["amazon_review_count"] = e.pop("review_count")
        return e
    return entry


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="data/amazon_history.json")
    p.add_argument("--output", default="data/japan-book.json")
    p.add_argument("--slug", default="japan-book")
    p.add_argument("--display-name", default="Things Become Other Things")
    p.add_argument("--commit", action="store_true",
                   help="Actually write output. Default is dry-run.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not SLUG_RE.match(args.slug):
        print(f"error: slug {args.slug!r} must match {SLUG_RE.pattern}", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"error: input not found: {input_path}", file=sys.stderr)
        return 1

    raw = json.loads(input_path.read_text())

    # Refuse if input is already wrapped (idempotency guard).
    if isinstance(raw, dict) and "slug" in raw and "entries" in raw:
        print(f"error: {input_path} looks already migrated (has 'slug' key). Refusing.", file=sys.stderr)
        return 1

    entries = raw.get("entries", [])
    original_count = len(entries)
    print(f"Loaded {original_count} entries from {input_path}")

    # Step 1: schema normalize
    normalized = [normalize_entry(e) for e in entries]
    normalized_changed = sum(1 for a, b in zip(entries, normalized) if a is not b)

    # Step 2: drop empty rankings
    non_empty = [e for e in normalized if e.get("rankings")]
    dropped_empty = len(normalized) - len(non_empty)

    # Step 3: dedupe consecutive identicals
    deduped = []
    prev_sig = None
    for e in non_empty:
        sig = entry_signature(e)
        if sig != prev_sig:
            deduped.append(e)
            prev_sig = sig
    collapsed = len(non_empty) - len(deduped)

    n = len(deduped)
    print("\nTransform summary:")
    print(f"  Original entries:                        {original_count}")
    print(f"  Schema-normalized (review_count -> new): {normalized_changed}")
    print(f"  Dropped (empty rankings):                {dropped_empty}")
    print(f"  Collapsed (consecutive duplicates):      {collapsed}")
    print(f"  Final entry count:                       {n}")

    # Samples for the eyeball test
    if dropped_empty:
        sample = next((e for e in normalized if not e.get("rankings")), None)
        if sample:
            print(f"\n  sample dropped: timestamp={sample.get('timestamp')}")
    if normalized_changed:
        sample = next((nb for a, nb in zip(entries, normalized) if a is not nb), None)
        if sample:
            print(f"  sample normalized: amazon_review_count={sample.get('amazon_review_count')!r}")

    # Build envelope
    last_ts = deduped[-1]["timestamp"] if deduped else None
    envelope = {
        "slug": args.slug,
        "display_name": args.display_name,
        "last_successful_scrape": last_ts,
        "last_error": None,
        "last_attempt_timestamp": last_ts,
        "last_attempt_status": "appended" if deduped else None,
        "entries": deduped,
    }

    print(f"\nEnvelope: slug={args.slug!r} display_name={args.display_name!r}")
    print(f"          last_successful_scrape={last_ts!r}")

    # Sanity check
    if not (SANITY_MIN <= n <= SANITY_MAX):
        print(f"\nSanity check FAILED: final count {n} not in [{SANITY_MIN}, {SANITY_MAX}]. Refusing.",
              file=sys.stderr)
        return 1

    if not args.commit:
        print("\n(dry-run) Not writing. Re-run with --commit to write.")
        return 0

    # Audit trail: hash the input BEFORE any side effects
    input_sha = sha256_file(input_path)
    input_mtime = input_path.stat().st_mtime

    write_atomic(output_path, envelope)

    if input_path.stat().st_mtime != input_mtime:
        print("warning: input file changed during migration — output may be stale", file=sys.stderr)

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "input_sha256": input_sha,
        "input_entry_count": original_count,
        "output_path": str(output_path),
        "output_entry_count": n,
        "normalized_schema": normalized_changed,
        "dropped_empty": dropped_empty,
        "collapsed_duplicates": collapsed,
        "slug": args.slug,
    }
    report_path = output_path.parent / "migration_report.json"
    write_atomic(report_path, report)

    # Invariant checks
    print("\nPost-migration invariants:")
    results = []

    def _check(label, ok):
        results.append(ok)
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")

    _check(f"count in [{SANITY_MIN}, {SANITY_MAX}]", SANITY_MIN <= n <= SANITY_MAX)
    _check("no entry has legacy 'review_count' key",
           all("review_count" not in e for e in deduped))
    _check("every entry has 'amazon_review_count'",
           all("amazon_review_count" in e for e in deduped))
    _check("no entry has empty rankings",
           all(e.get("rankings") for e in deduped))

    timestamps = [e["timestamp"] for e in deduped]
    _check("timestamps non-decreasing",
           all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1)))

    src_cats = {r["category"] for e in entries for r in e.get("rankings", [])}
    out_cats = {r["category"] for e in deduped for r in e.get("rankings", [])}
    missing = src_cats - out_cats
    _check(f"no category vanished (missing: {missing or 'none'})", not missing)

    first_surviving = next((e for e in normalized if e.get("rankings")), None)
    last_surviving = next((e for e in reversed(normalized) if e.get("rankings")), None)
    if first_surviving and last_surviving and deduped:
        _check("first timestamp preserved",
               deduped[0]["timestamp"] == first_surviving["timestamp"])
        # Dedupe keeps the FIRST occurrence of each run, so the tail entry's
        # timestamp may be earlier than the source's last timestamp. What must
        # survive is the latest observed STATE — check signatures, not timestamps.
        _check("latest state preserved (signature)",
               entry_signature(deduped[-1]) == entry_signature(last_surviving))

    print(f"\nWrote {output_path} ({n} entries)")
    print(f"Wrote {report_path}")
    passed = sum(results)
    failed = len(results) - passed
    print(f"Invariants: {passed} passed, {failed} failed")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
