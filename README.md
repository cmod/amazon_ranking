# Amazon Book Ranking Tracker

Track your Amazon book sales rankings and review metrics over time with interactive visualizations.

## Features

- **Multi-Category Tracking**: Captures overall Books ranking plus all sub-category rankings
- **Review Count Monitoring**: Tracks review growth over time
- **Interactive Dashboard**: Individual charts for each category (colorblind-friendly)
- **Multiple Data Formats**: JSON for dashboard, CSV for analysis
- **Template-Based**: Easy to customize dashboard appearance

## Quick Start

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Your Book**
   - Edit `amazon.py` and update the `URL` variable with your book's Amazon page
   - Currently set to: `https://www.amazon.com/dp/0593732545`

3. **Run the Tracker**
   ```bash
   # Default - creates index.html in current directory
   python amazon.py
   
   # Or specify custom output directory
   python amazon.py --output-dir /path/to/web/root
   python amazon.py -o ./public
   ```

4. **View Dashboard**
   - Open `index.html` in your browser
   - Data is stored in the `data/` directory

## File Structure

```
amazon_ranking/
├── amazon.py                    # Main scraper script
├── dashboard_template.html      # HTML template for dashboard
├── index.html                   # Generated interactive dashboard
├── requirements.txt             # Python dependencies
├── data/                        # Data storage directory
│   ├── amazon_history.json     # JSON data for dashboard
│   └── amazon_detailed_history.csv  # Detailed CSV format
└── CLAUDE.md                   # Development documentation
```

## Server Deployment

### Option 1: Simple Python Server
```bash
# Install dependencies
pip install -r requirements.txt

# Run scraper (creates data/ directory automatically)
python amazon.py

# Serve dashboard (optional)
python -m http.server 8000
# Access at http://localhost:8000
```

### Option 2: Cron Job for Regular Updates

**Option A: Using system Python (after pip install -r requirements.txt)**
```bash
# Add to crontab for every 6 hours
0 */6 * * * cd /path/to/amazon_ranking && /usr/bin/python3 amazon.py

# Or with custom output directory (e.g., web server root)
0 */6 * * * cd /path/to/amazon_ranking && /usr/bin/python3 amazon.py --output-dir /var/www/html
```

**Option B: Using virtual environment**
```bash
# Add to crontab - activate venv first
0 */6 * * * cd /path/to/amazon_ranking && source venv/bin/activate && python amazon.py -o /var/www/html

# Or use direct path to venv python
0 */6 * * * cd /path/to/amazon_ranking && ./venv/bin/python amazon.py --output-dir /var/www/html
```

**To edit crontab:**
```bash
crontab -e
```

### Option 3: Web Server (nginx/Apache)
- Place files in web root directory
- Set up cron job to run `python amazon.py` regularly
- Serve `index.html` as static file

## Data Outputs

- **`data/amazon_history.json`**: Structured data for dashboard
- **`index.html`**: Interactive dashboard with Chart.js visualizations
- **`data/amazon_detailed_history.csv`**: CSV format for spreadsheet analysis

## Customization

### Dashboard Appearance
Edit `dashboard_template.html` to customize:
- Colors and styling (CSS)
- Chart configurations
- Layout and design

### Target Book
Update the `URL` constant in `amazon.py`:
```python
URL = "https://www.amazon.com/dp/YOUR_BOOK_ID"
```

## Command Line Options

```bash
# Show help
python amazon.py --help

# Specify output directory for index.html
python amazon.py --output-dir /path/to/directory
python amazon.py -o ./public

# Examples:
python amazon.py -o /var/www/html        # Web server root
python amazon.py -o ~/Desktop/dashboard  # Desktop folder
python amazon.py -o ./build              # Build directory
```

## Dependencies

- **requests**: HTTP requests to Amazon
- **beautifulsoup4**: HTML parsing and data extraction
- **Chart.js**: Interactive charts (loaded via CDN)

## Troubleshooting

- **No rankings found**: Amazon may have changed their HTML structure
- **Bot detection**: The script uses browser-like headers to avoid detection
- **Missing data**: Ensure the Amazon URL is correct and accessible

## Current Example Data

The tracker currently monitors these categories:
- Overall Books ranking (e.g., #17031 in Books)
- General Japan Travel Guides (e.g., #4)
- Traveler & Explorer Biographies (e.g., #63)
- Memoirs (e.g., #315)
- Review count tracking (e.g., 37 reviews)

