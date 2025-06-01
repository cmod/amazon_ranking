# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python script for tracking Amazon book sales ranking and review metrics over time. The script scrapes Amazon product pages to extract Best Sellers Rank information across multiple categories and review counts, logging detailed data to CSV files with timestamps.

## Architecture

- **amazon.py**: Main script containing web scraping logic and multiple data output formats
  - `get_book_data()`: Main data collection function that coordinates scraping
  - `get_all_rankings()`: Scrapes Amazon page for all category rankings using BeautifulSoup
  - `get_review_count()`: Extracts current review count from product page
  - `save_book_data_json()`: Saves structured data to JSON format for dashboard
  - `save_book_data()`: Appends detailed timestamp, review count, and ranking data to CSV
  - `generate_html_report()`: Creates interactive HTML dashboard with Chart.js graphs
  - `save_ranking()`: Legacy function for backward compatibility
  - `main()`: Orchestrates data fetch, save in multiple formats, and dashboard generation

- **data/amazon_history.json**: Primary JSON data store with structured entries for dashboard
- **dashboard_template.html**: HTML template file with Chart.js integration and placeholder for data
- **index.html**: Generated interactive HTML dashboard with embedded data
- **data/amazon_detailed_history.csv**: CSV format with columns: timestamp, review_count, category, rank
- **data/amazon_rank_history.csv**: Legacy format maintained for backward compatibility

## Development Commands

### Environment Setup
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies (if needed)
pip install requests beautifulsoup4
```

### Running the Script
```bash
# Run the ranking tracker
python amazon.py
```

## Key Implementation Details

- Uses requests with browser-like headers to avoid bot detection
- Searches for "Best Sellers Rank" text in HTML and extracts all category rankings
- Extracts review counts using multiple regex patterns across page elements
- Robust error handling with fallback patterns for data extraction
- Appends data to CSV rather than overwriting (preserves historical data)
- Removes duplicate rankings while preserving order
- Target URL is hardcoded for specific book: https://www.amazon.com/dp/0593732545

## Data Output

The enhanced scraper captures:
- Overall Amazon Books ranking (e.g., #17031 in Books)
- Sub-category rankings (e.g., #4 in General Japan Travel Guides, #63 in Traveler & Explorer Biographies)
- Current review count (e.g., 37 reviews)
- Timestamp for each data collection run

## Interactive Dashboard

The script automatically generates `amazon_ranking_dashboard.html` with:
- **Interactive Charts**: Line graphs showing ranking trends over time for each category
- **Review Count Tracking**: Visual representation of review growth
- **Current Stats Cards**: Latest rankings and review count at a glance
- **Responsive Design**: Works on desktop and mobile devices
- **Chart.js Integration**: Professional, interactive charts with hover tooltips

Open `index.html` in any web browser to view the dashboard.

## Dependencies

- requests: HTTP requests to Amazon
- beautifulsoup4: HTML parsing and data extraction
- csv, datetime, re, os, json: Built-in Python modules for data handling, regex processing, and JSON operations

## File Outputs

- **data/amazon_history.json**: Structured JSON data for dashboard consumption
- **dashboard_template.html**: Reusable HTML template with Chart.js and {{DATA_PLACEHOLDER}}
- **index.html**: Self-contained HTML dashboard with embedded data
- **data/amazon_detailed_history.csv**: CSV format for spreadsheet analysis
- **data/amazon_rank_history.csv**: Legacy CSV format for backward compatibility

## Template System

The dashboard uses a template-based approach:
- **dashboard_template.html**: Contains the HTML structure, CSS styling, and JavaScript logic
- **{{DATA_PLACEHOLDER}}**: Marker replaced with actual JSON data during generation
- This separation allows easy customization of dashboard appearance without modifying Python code