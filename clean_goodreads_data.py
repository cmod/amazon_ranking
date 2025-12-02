#!/usr/bin/env python3
"""
Clean up bad Goodreads data in amazon_history.json.
This script removes Goodreads ratings/reviews that are suspiciously high
(likely Amazon rankings that were incorrectly captured).
"""

import json
import shutil
from datetime import datetime

JSON_FILE = "data/amazon_history.json"
BACKUP_FILE = f"data/amazon_history_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# Thresholds for what we consider "bad" data
MAX_REASONABLE_RATINGS = 10000  # If ratings > 10k, probably a ranking number
MAX_REASONABLE_REVIEWS = 5000   # If reviews > 5k, probably a ranking number

def clean_data():
    """Clean the Goodreads data in the JSON file."""

    # Read the current data
    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    # Create backup
    print(f"Creating backup: {BACKUP_FILE}")
    shutil.copy2(JSON_FILE, BACKUP_FILE)

    entries = data.get('entries', [])
    cleaned_count = 0

    print(f"\nAnalyzing {len(entries)} entries...")

    for i, entry in enumerate(entries):
        ratings = entry.get('goodreads_ratings_count')
        reviews = entry.get('goodreads_reviews_count')

        # Check if we have suspicious data
        needs_cleaning = False

        if ratings:
            ratings_int = int(ratings)
            if ratings_int > MAX_REASONABLE_RATINGS:
                print(f"Entry {i+1} ({entry['timestamp']}): Bad ratings count {ratings} - removing")
                needs_cleaning = True

        if reviews:
            reviews_int = int(reviews)
            if reviews_int > MAX_REASONABLE_REVIEWS:
                print(f"Entry {i+1} ({entry['timestamp']}): Bad reviews count {reviews} - removing")
                needs_cleaning = True

        # Clean the entry if needed
        if needs_cleaning:
            if 'goodreads_ratings_count' in entry:
                del entry['goodreads_ratings_count']
            if 'goodreads_reviews_count' in entry:
                del entry['goodreads_reviews_count']
            cleaned_count += 1

    if cleaned_count > 0:
        # Save cleaned data
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\n✓ Cleaned {cleaned_count} entries")
        print(f"✓ Backup saved to: {BACKUP_FILE}")
        print(f"✓ Updated file: {JSON_FILE}")
    else:
        print("\n✓ No bad data found - all entries look good!")

    # Show summary statistics
    print("\n=== Summary Statistics ===")
    ratings_counts = []
    reviews_counts = []

    for entry in entries:
        if entry.get('goodreads_ratings_count'):
            ratings_counts.append(int(entry['goodreads_ratings_count']))
        if entry.get('goodreads_reviews_count'):
            reviews_counts.append(int(entry['goodreads_reviews_count']))

    if ratings_counts:
        print(f"Goodreads Ratings: min={min(ratings_counts)}, max={max(ratings_counts)}, count={len(ratings_counts)}")
    if reviews_counts:
        print(f"Goodreads Reviews: min={min(reviews_counts)}, max={max(reviews_counts)}, count={len(reviews_counts)}")

if __name__ == "__main__":
    clean_data()
