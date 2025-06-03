import requests
from bs4 import BeautifulSoup
from datetime import datetime
import csv
import re
import os
import json
import argparse

# URL of your book's Amazon page
AMAZON_URL = "https://www.amazon.com/dp/0593732545"

# URL of your book's Goodreads page
GOODREADS_URL = "https://www.goodreads.com/book/show/217245583"

# Headers to mimic a browser visit (helps avoid bot detection)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}

def get_amazon_data():
    response = requests.get(AMAZON_URL, headers=HEADERS)
    if response.status_code != 200:
        print("Failed to fetch Amazon page")
        return None

    soup = BeautifulSoup(response.content, "html.parser")
    
    data = {
        'rankings': [],
        'amazon_review_count': None,
        'overall_rank': None
    }
    
    # Get review count
    review_count = get_amazon_review_count(soup)
    data['amazon_review_count'] = review_count
    
    # Get all rankings (overall + sub-categories)
    rankings = get_all_rankings(soup)
    data['rankings'] = rankings
    
    return data

def get_goodreads_data():
    response = requests.get(GOODREADS_URL, headers=HEADERS)
    if response.status_code != 200:
        print("Failed to fetch Goodreads page")
        return None

    soup = BeautifulSoup(response.content, "html.parser")
    
    data = {
        'goodreads_ratings_count': None,
        'goodreads_reviews_count': None
    }
    
    # Get ratings and reviews count
    ratings_count = get_goodreads_ratings_count(soup)
    reviews_count = get_goodreads_reviews_count(soup)
    
    data['goodreads_ratings_count'] = ratings_count
    data['goodreads_reviews_count'] = reviews_count
    
    return data

def get_book_data():
    # Get data from both Amazon and Goodreads
    amazon_data = get_amazon_data()
    goodreads_data = get_goodreads_data()
    
    # Combine the data
    combined_data = {}
    if amazon_data:
        combined_data.update(amazon_data)
    if goodreads_data:
        combined_data.update(goodreads_data)
    
    return combined_data if combined_data else None

def get_amazon_review_count(soup):
    try:
        # Look for review count in various formats and locations
        review_patterns = [
            r'(\d{1,3}(?:,\d{3})*)\s*(?:customer\s*)?reviews?',
            r'(\d{1,3}(?:,\d{3})*)\s*ratings?',
            r'(\d{1,3}(?:,\d{3})*)\s*global\s*ratings?'
        ]
        
        # Check various elements where review count might appear
        selectors = [
            '[data-hook*="reviews"]',
            '[data-hook*="rating"]',
            '[id*="reviews"]',
            '[class*="reviews"]',
            'span:contains("reviews")',
            'span:contains("ratings")',
            'a[href*="reviews"]'
        ]
        
        for pattern in review_patterns:
            # Check in specific data attributes
            for element in soup.find_all(attrs={'data-hook': True}):
                if any(keyword in element.get('data-hook', '').lower() 
                       for keyword in ['reviews', 'rating', 'total']):
                    text = element.get_text()
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1).replace(',', '')
            
            # Check in all text content for review patterns
            page_text = soup.get_text()
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                # Return the first reasonable number (not too large)
                for match in matches:
                    num = int(match.replace(',', ''))
                    if 1 <= num <= 1000000:  # Reasonable review count range
                        return str(num)
        
        return None
    except Exception as e:
        print(f"Error extracting Amazon review count: {e}")
        return None

def get_goodreads_ratings_count(soup):
    try:
        # Look for ratings count in various patterns
        patterns = [
            r'(\d{1,3}(?:,\d{3})*)\s*ratings?',
            r'(\d{1,3}(?:,\d{3})*)\s*people\s*rated',
        ]
        
        # Check in data attributes and spans
        for element in soup.find_all(['span', 'div', 'a']):
            text = element.get_text()
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    num = int(match.group(1).replace(',', ''))
                    if 1 <= num <= 10000000:  # Reasonable range
                        return str(num)
        
        # Check for specific Goodreads data attributes
        for element in soup.find_all(attrs={'data-testid': True}):
            if 'rating' in element.get('data-testid', '').lower():
                text = element.get_text()
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1).replace(',', '')
        
        return None
    except Exception as e:
        print(f"Error extracting Goodreads ratings count: {e}")
        return None

def get_goodreads_reviews_count(soup):
    try:
        # Look for reviews count
        patterns = [
            r'(\d{1,3}(?:,\d{3})*)\s*reviews?',
            r'(\d{1,3}(?:,\d{3})*)\s*people\s*reviewed',
        ]
        
        # Check in various elements
        for element in soup.find_all(['span', 'div', 'a']):
            text = element.get_text()
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    num = int(match.group(1).replace(',', ''))
                    if 1 <= num <= 1000000:  # Reasonable range for reviews
                        return str(num)
        
        # Check for specific Goodreads data attributes
        for element in soup.find_all(attrs={'data-testid': True}):
            if 'review' in element.get('data-testid', '').lower():
                text = element.get_text()
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1).replace(',', '')
        
        return None
    except Exception as e:
        print(f"Error extracting Goodreads reviews count: {e}")
        return None

def get_all_rankings(soup):
    rankings = []
    
    try:
        # Find Best Sellers Rank section
        rank_section = soup.find(string=lambda t: t and "Best Sellers Rank" in t)
        if not rank_section:
            print("Sales rank not found.")
            return rankings
        
        # Get the parent element containing all ranking info
        rank_container = rank_section.parent
        
        # Traverse up to find a container with ranking information
        max_traversals = 5
        traversal_count = 0
        while (rank_container and 
               traversal_count < max_traversals and 
               not rank_container.find_all(['li', 'span'])):
            rank_container = rank_container.parent
            traversal_count += 1
        
        if not rank_container:
            print("Could not find ranking container.")
            return rankings
        
        # Extract rankings from the container
        rank_text = rank_container.get_text()
        
        # Parse different ranking formats with improved patterns
        rank_patterns = [
            # Pattern for "#4 in General Japan Travel Guides" or "#123,456 in Books (See Top 100)"
            r'#([\d,]+)\s+in\s+([^#\n]+?)(?=\s*(?:#|\s*$))',
        ]
        
        for pattern in rank_patterns:
            matches = re.findall(pattern, rank_text, re.MULTILINE | re.IGNORECASE)
            for rank_num, category in matches:
                # Clean up category text
                cleaned_category = category.strip()
                # Remove trailing parenthetical info like "(See Top 100 in Books)"
                cleaned_category = re.sub(r'\s*\([^)]*\)\s*$', '', cleaned_category)
                cleaned_category = cleaned_category.strip()
                
                if cleaned_category and rank_num and len(cleaned_category) < 100:  # Sanity check
                    rankings.append({
                        'rank': rank_num.replace(',', ''),
                        'category': cleaned_category
                    })
        
        # Remove duplicates while preserving order
        seen_categories = set()
        unique_rankings = []
        for ranking in rankings:
            if ranking['category'] not in seen_categories:
                seen_categories.add(ranking['category'])
                unique_rankings.append(ranking)
        
        return unique_rankings
        
    except Exception as e:
        print(f"Error extracting rankings: {e}")
        return rankings

def save_book_data_json(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = "data/amazon_history.json"
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    # Create entry for this data collection
    entry = {
        'timestamp': now,
        'amazon_review_count': data.get('amazon_review_count'),
        'goodreads_ratings_count': data.get('goodreads_ratings_count'),
        'goodreads_reviews_count': data.get('goodreads_reviews_count'),
        'rankings': data.get('rankings', [])
    }
    
    # Load existing data or create new structure
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            try:
                history_data = json.load(file)
            except json.JSONDecodeError:
                history_data = {'entries': []}
    else:
        history_data = {'entries': []}
    
    # Add new entry
    history_data['entries'].append(entry)
    
    # Save updated data
    with open(filename, 'w') as file:
        json.dump(history_data, file, indent=2)

def save_book_data(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = "data/amazon_detailed_history.csv"
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    # Check if file exists and is empty to write header
    write_header = not os.path.exists(filename) or os.path.getsize(filename) == 0
    
    # Create detailed CSV with all rankings and review count
    with open(filename, mode="a", newline="") as file:
        writer = csv.writer(file)
        
        # Write header if file is new/empty
        if write_header:
            writer.writerow(["timestamp", "amazon_review_count", "goodreads_ratings_count", "goodreads_reviews_count", "category", "rank"])
        
        # Write review/rating counts and each ranking as separate rows
        amazon_review_count = data.get('amazon_review_count', 'N/A')
        goodreads_ratings_count = data.get('goodreads_ratings_count', 'N/A')
        goodreads_reviews_count = data.get('goodreads_reviews_count', 'N/A')
        
        if data.get('rankings'):
            for ranking in data['rankings']:
                writer.writerow([
                    now,
                    amazon_review_count,
                    goodreads_ratings_count,
                    goodreads_reviews_count,
                    ranking['category'],
                    ranking['rank']
                ])
        else:
            # If no rankings found, still record review/rating counts
            writer.writerow([now, amazon_review_count, goodreads_ratings_count, goodreads_reviews_count, 'N/A', 'N/A'])

def generate_html_report(output_dir="."):
    """Generate HTML file with interactive charts showing ranking history"""
    
    # Load JSON data
    json_filename = "data/amazon_history.json"
    if not os.path.exists(json_filename):
        print("No JSON data file found. Run the scraper first.")
        return
    
    with open(json_filename, 'r') as file:
        history_data = json.load(file)
    
    # Load HTML template
    template_filename = "dashboard_template.html"
    if not os.path.exists(template_filename):
        print(f"Template file {template_filename} not found.")
        return
    
    with open(template_filename, 'r') as file:
        html_template = file.read()
    
    # Replace placeholder with actual data
    html_content = html_template.replace(
        '{{DATA_PLACEHOLDER}}', 
        json.dumps(history_data, indent=2)
    )
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Write HTML file to specified directory
    output_file = os.path.join(output_dir, "index.html")
    with open(output_file, "w") as file:
        file.write(html_content)
    
    print(f"HTML dashboard generated: {output_file}")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Amazon Book Ranking Tracker')
    parser.add_argument('--output-dir', '-o', 
                       default='.', 
                       help='Output directory for index.html (default: current directory)')
    
    args = parser.parse_args()
    
    print("Fetching Amazon book data...")
    data = get_book_data()
    
    if data:
        print(f"\nData collected at {datetime.now()}:")
        print(f"Amazon review count: {data.get('amazon_review_count', 'Not found')}")
        print(f"Goodreads ratings count: {data.get('goodreads_ratings_count', 'Not found')}")
        print(f"Goodreads reviews count: {data.get('goodreads_reviews_count', 'Not found')}")
        
        if data.get('rankings'):
            print("Amazon Rankings:")
            for ranking in data['rankings']:
                print(f"  #{ranking['rank']} in {ranking['category']}")
        else:
            print("No Amazon rankings found")
        
        # Save data in multiple formats
        save_book_data_json(data)
        print(f"\nData saved to data/amazon_history.json")
        
        save_book_data(data)
        print(f"Data saved to data/amazon_detailed_history.csv")
        
        # Generate HTML dashboard in specified directory
        generate_html_report(args.output_dir)
    else:
        print("Failed to fetch book data")

if __name__ == "__main__":
    main()
