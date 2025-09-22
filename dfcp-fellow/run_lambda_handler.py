# Web Scraper for Google News RSS Feeds
import json
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone
import logging
import os
import warnings
from dateutil import parser as date_parser
import time

# Suppress BeautifulSoup XML parsing warnings for cleaner output
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Configure logging with timestamp and level information
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Local directory configuration for storing scraped data
SCRAPED_DATA_DIR = "scraped_data"

# Google News RSS URLs for different Turkish news categories
# Each URL is configured for Turkish language (hl=tr) and Turkey region (gl=TR)
NEWS_CATEGORIES = {
    
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}

def init_local_directory():
    """
    Initialize local directory structure for data storage.
    
    Creates the 'scraped_data' directory if it doesn't exist.
    This directory will store all JSON files containing scraped news data.
    
    Returns:
        None
        
    Logs:
        Info message about directory creation or existence
    """
    if not os.path.exists(SCRAPED_DATA_DIR):
        os.makedirs(SCRAPED_DATA_DIR)
        logger.info(f"Directory created: {SCRAPED_DATA_DIR}")
    else:
        logger.info(f"Directory already exists: {SCRAPED_DATA_DIR}")

def is_within_last_hour(published_date_str):
    """
    Check if a news article was published within the last hour.
    
    This function helps filter recent news by comparing the publication date
    with the current UTC time. Only articles published in the last 60 minutes
    will be considered for processing.
    
    Args:
        published_date_str (str): Publication date string from RSS feed
        
    Returns:
        bool: True if article was published within last hour, False otherwise
        
    Note:
        Returns False for invalid or missing dates to avoid processing errors
    """
    if not published_date_str: 
        return False
    
    try:
        # Parse the publication date and convert to UTC timezone
        pub_date = date_parser.parse(published_date_str).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        
        # Calculate time difference in seconds and check if within 1 hour (3600 seconds)
        return (now_utc - pub_date).total_seconds() <= 3600
    except Exception: 
        # Return False for any parsing errors to maintain stability
        return False

def extract_article_data(item):
    """
    Extract structured article data from RSS item element.
    
    This function parses RSS feed items and extracts relevant information
    including title, URL, description, source, and publication date.
    It handles the specific format used by Google News RSS feeds.
    
    Args:
        item: BeautifulSoup element representing a single RSS item
        
    Returns:
        dict: Structured article data with keys:
            - title: Article headline (cleaned)
            - url: Direct link to the article
            - short_description: Brief description or excerpt
            - source: News source/publisher name
            - published_date: Publication timestamp string
        None: If data extraction fails
        
    Note:
        Google News RSS feeds contain embedded HTML in descriptions,
        which requires additional parsing to extract clean URLs and text.
    """
    try:
        # Extract full title which typically contains "Title - Source" format
        full_title = item.find('title').get_text(strip=True)
        
        # Split title and source if separator exists
        if ' - ' in full_title:
            title, source = full_title.rsplit(' - ', 1)
        else:
            title = full_title
            # Fallback to source tag if title doesn't contain source
            source = item.find('source').get_text(strip=True) if item.find('source') else "Bilinmiyor"
        
        # Parse description HTML to extract article URL and description text
        description_html = BeautifulSoup(item.find('description').get_text(strip=True), 'html.parser')
        link_tag = description_html.find('a')

        return {
            'title': title.strip(),
            'url': link_tag['href'] if link_tag else item.find('link').get_text(strip=True),
            'short_description': link_tag.get_text(strip=True) if link_tag else "",
            'source': source.strip(),
            'published_date': item.find('pubdate').get_text(strip=True) if item.find('pubdate') else None
        }
    except Exception as e:
        # Log warning but continue processing other articles
        logger.warning(f"Error extracting article data: {e}")
        return None

def scrape_category(category_name, rss_url):
    """
    Scrape news articles from a specific category RSS feed.
    
    This function fetches and parses RSS feeds for a given news category,
    extracting articles published within the last hour. It includes proper
    error handling and user-agent headers for reliable scraping.
    
    Args:
        category_name (str): Human-readable category name for logging
        rss_url (str): Google News RSS feed URL for the category
        
    Returns:
        list: List of article dictionaries with added rank information
              Each article includes original data plus 'rank' field
              indicating its position in the feed
        
    Note:
        Uses HTML parser instead of XML parser for better compatibility
        with Google News RSS feed format. Articles are ranked by their
        position in the original RSS feed.
    """
    # Set user agent to avoid being blocked by Google's servers
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)'}
    
    try:
        logger.info(f"Scraping category: {category_name}")
        
        # Fetch RSS feed with timeout to prevent hanging
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse RSS content using HTML parser for better Google News compatibility
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item')
        
        articles = []
        # Process each RSS item and filter by publication time
        for index, item in enumerate(items):
            article_data = extract_article_data(item)
            
            # Only include articles published within the last hour
            if article_data and is_within_last_hour(article_data['published_date']):
                # Add ranking information based on RSS feed position
                article_data['rank'] = index + 1
                articles.append(article_data)
        
        logger.info(f"✅ {category_name}: {len(articles)} recent articles found")
        return articles
        
    except Exception as e:
        # Log error but don't crash the entire scraping process
        logger.error(f"❌ Error scraping {category_name} category: {e}")
        return []

def save_data_to_local_file(all_scraped_data, scraped_at):
    """
    Save scraped news data to local JSON file.
    
    This function writes the complete scraped dataset to a timestamped
    JSON file in the local scraped_data directory. The file includes
    proper UTF-8 encoding to handle Turkish characters correctly.
    
    Args:
        all_scraped_data (dict): Complete dataset including all categories
        scraped_at (datetime): Timestamp when scraping was performed
        
    Returns:
        bool: True if file was saved successfully, False otherwise
        
    Note:
        File naming convention: google_news_YYYY-MM-DD_HH-MM-SS.json
        Uses ensure_ascii=False to properly handle Turkish characters
    """
    try:
        # Generate timestamped filename for uniqueness and organization
        file_name = f"google_news_{scraped_at.strftime('%Y-%m-%d_%H-%M-%S')}.json"
        file_path = os.path.join(SCRAPED_DATA_DIR, file_name)
        
        # Write JSON data with proper UTF-8 encoding and formatting
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(all_scraped_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📦 Data saved to local file: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving data to local file: {e}")
        return False

def main():
    """
    Main execution function for the news scraper.
    
    This function orchestrates the entire scraping process:
    1. Initializes local directory structure
    2. Iterates through all news categories
    3. Scrapes recent articles from each category
    4. Aggregates all data into a single structure
    5. Saves results to timestamped JSON file
    6. Provides comprehensive execution summary
    
    Returns:
        dict: Execution summary containing:
            - statusCode: HTTP-style status code (200 for success)
            - message: Human-readable summary
            - total_articles: Total number of articles scraped
            - categories_processed: Number of categories successfully processed
            
    Note:
        Includes small delays between category requests to be respectful
        to Google's servers and avoid rate limiting.
    """
    start_time = time.time()
    logger.info("🚀 Local News Scraper started - Enhanced Parser Version")

    # Initialize local storage directory
    init_local_directory()
    
    # Create timestamp for this scraping session
    scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Initialize data structure for aggregated results
    all_scraped_data = {
        "scrape_timestamp_utc": scraped_at.isoformat(),
        "categories": {}
    }
    
    total_articles_scraped = 0
    
    # Process each news category sequentially
    for category_name, rss_url in NEWS_CATEGORIES.items():
        # Scrape articles from current category
        articles = scrape_category(category_name, rss_url)
        
        # Add category data to aggregated results
        all_scraped_data["categories"][category_name] = articles
        total_articles_scraped += len(articles)
        
        # Brief delay to be respectful to Google's servers
        time.sleep(0.2)

    # Save aggregated data to local JSON file
    save_success = save_data_to_local_file(all_scraped_data, scraped_at)

    # Calculate execution metrics
    elapsed_time = time.time() - start_time
    
    # Create comprehensive execution summary
    summary = (
        f"🏁 SUMMARY: {len(all_scraped_data['categories'])}/{len(NEWS_CATEGORIES)} categories processed. "
        f"Total {total_articles_scraped} articles scraped. "
        f"File save: {'✅ Success' if save_success else '❌ Failed'}. "
        f"Duration: {elapsed_time:.2f}s"
    )
    
    logger.info(summary)
    
    # Return structured result for potential API usage
    return {
        'statusCode': 200,
        'message': summary,
        'total_articles': total_articles_scraped,
        'categories_processed': len(all_scraped_data['categories'])
    }

# Entry point for script execution
if __name__ == "__main__":
    """
    Script entry point when run directly.
    
    Executes the main scraping function and displays the final summary.
    This allows the script to be run standalone or imported as a module.
    """
    result = main()
    print(f"\n{result['message']}")