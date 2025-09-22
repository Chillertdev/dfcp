"""
AWS Lambda News Scraper for Google News RSS Feeds

This AWS Lambda function provides a comprehensive solution for scraping Turkish news articles
from Google News RSS feeds, storing them in RDS MySQL database and backing up to S3.
It filters articles published within the last hour and includes robust error handling
and performance optimizations for cloud deployment.

Features:
- Multi-category news scraping (World, Sports, Business, Technology, Entertainment, Health)
- Time-based filtering (last hour only)
- MySQL database storage with optimized batch operations
- S3 backup with timestamped JSON files
- Comprehensive error handling and logging
- AWS Lambda optimized execution
- Turkish language support with proper encoding

Author: AWS News Scraping Team
Version: 2.1
Last Modified: 2025
AWS Services: Lambda, RDS MySQL, S3
"""

import json
import boto3
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone
import logging
import os
import warnings
from dateutil import parser as date_parser
import pymysql
import time

# Suppress BeautifulSoup XML parsing warnings for cleaner Lambda logs
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Configure AWS Lambda logging with appropriate level
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS S3 configuration for data backup storage
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'dfcp-scraped-bucket')
s3_client = boto3.client('s3')

# RDS MySQL configuration from Lambda environment variables
# These should be set in Lambda function configuration
RDS_HOST = os.environ.get('RDS_HOST')
RDS_USERNAME = os.environ.get('RDS_USERNAME') 
RDS_PASSWORD = os.environ.get('RDS_PASSWORD')
RDS_DATABASE = os.environ.get('RDS_DATABASE', 'news_db')
RDS_PORT = int(os.environ.get('RDS_PORT', 3306))

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

def get_mysql_connection():
    """
    Establish connection to AWS RDS MySQL database.
    
    Creates a connection to the RDS MySQL instance using environment variables
    for configuration. Includes connection timeout and proper character encoding
    for Turkish text handling.
    
    Returns:
        pymysql.Connection: Active database connection with UTF-8 support
        
    Raises:
        Exception: If connection cannot be established
        
    Note:
        Uses DictCursor for easier result handling and 10-second timeout
        to prevent Lambda function hanging on connection issues.
    """
    try:
        connection = pymysql.connect(
            host=RDS_HOST, 
            user=RDS_USERNAME, 
            password=RDS_PASSWORD,
            database=RDS_DATABASE, 
            port=RDS_PORT, 
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor, 
            connect_timeout=10
        )
        logger.info("MySQL connection established successfully")
        return connection
    except Exception as e:
        logger.error(f"MySQL connection error: {e}")
        raise

def init_database():
    """
    Initialize database schema for news storage.
    
    Creates the news_articles table if it doesn't exist, with optimized
    indexes for common query patterns. Includes proper UTF-8 collation
    for Turkish character support and unique constraints to prevent duplicates.
    
    Returns:
        None
        
    Raises:
        Exception: If table creation fails
        
    Note:
        Table design optimized for time-series queries and category filtering.
        Includes composite unique key on URL and scraped_at to handle URL reuse.
    """
    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            # Create optimized table schema with proper indexes
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS news_articles (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(1000) NOT NULL, 
                url VARCHAR(1024) NOT NULL,
                short_description TEXT, 
                source VARCHAR(255), 
                category VARCHAR(50) NOT NULL,
                published_date DATETIME, 
                rank_position INT, 
                scraped_at DATETIME NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_category_scraped (category, scraped_at),
                INDEX idx_source_scraped (source, scraped_at),
                INDEX idx_rank_scraped (rank_position, scraped_at),
                UNIQUE KEY uk_url_scraped_at (url(255), scraped_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
            cursor.execute(create_table_sql)
            connection.commit()
            logger.info("Database table initialized or already exists")
    finally:
        connection.close()

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
        Returns False for invalid or missing dates to avoid processing errors.
        Uses UTC timezone for consistent comparison across regions.
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
        
        # Fetch RSS feed with timeout to prevent Lambda hanging
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

def save_articles_to_mysql(articles, category, scraped_at):
    """
    Save scraped articles to MySQL database using batch operations.
    
    This function performs optimized batch insertion of articles into the
    MySQL database. Uses INSERT IGNORE to handle duplicate URLs gracefully
    and includes proper date parsing for database storage.
    
    Args:
        articles (list): List of article dictionaries to save
        category (str): Category name for the articles
        scraped_at (datetime): Timestamp when scraping was performed
        
    Returns:
        int: Number of articles successfully inserted (may be less than
             input if duplicates were ignored)
        
    Note:
        Uses executemany for better performance with multiple records.
        Handles date parsing errors gracefully by skipping problematic articles.
    """
    if not articles: 
        return 0
        
    connection = get_mysql_connection()
    
    # Prepared statement for batch insertion with duplicate handling
    insert_sql = """
    INSERT IGNORE INTO news_articles 
    (title, url, short_description, source, category, published_date, rank_position, scraped_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    values_to_insert = []
    
    # Prepare data for batch insertion with proper date handling
    for article in articles:
        try:
            # Parse and normalize publication date to UTC datetime
            published_datetime = (
                date_parser.parse(article['published_date'])
                .astimezone(timezone.utc)
                .replace(tzinfo=None) 
                if article['published_date'] 
                else None
            )
            
            values_to_insert.append((
                article['title'], 
                article['url'], 
                article.get('short_description'),
                article['source'], 
                category, 
                published_datetime, 
                article.get('rank'), 
                scraped_at
            ))
        except Exception as e:
            logger.warning(f"Data preparation error for article '{article.get('title')}': {e}")

    if not values_to_insert:
        connection.close()
        return 0

    try:
        with connection.cursor() as cursor:
            # Execute batch insertion
            result = cursor.executemany(insert_sql, values_to_insert)
            connection.commit()
            logger.info(f"💾 MySQL batch save: {result}/{len(values_to_insert)} articles ({category})")
            return result
    except Exception as e:
        logger.error(f"MySQL batch save error ({category}): {e}")
        return 0
    finally:
        connection.close()

def lambda_handler(event, context):
    """
    AWS Lambda main handler function.
    
    This is the entry point for the Lambda function execution. It orchestrates
    the entire news scraping process including database initialization,
    category processing, data storage, and S3 backup. Includes comprehensive
    error handling and execution time monitoring for AWS Lambda constraints.
    
    Args:
        event (dict): Lambda event data (not used in this implementation)
        context (object): Lambda runtime context with execution metadata
        
    Returns:
        dict: HTTP-style response with:
            - statusCode: 200 for success, 500 for errors
            - body: JSON string containing execution summary or error details
            
    Note:
        Monitors execution time to stay within Lambda timeout limits.
        Implements graceful degradation if time limits are approached.
        Saves backup to S3 regardless of database operation success.
    """
    start_time = time.time()
    logger.info("🚀 Lambda function started - Enhanced Parser with DB Optimization")

    # Initialize database schema (create tables if needed)
    try:
        init_database()
    except Exception as e:
        # Return early if database initialization fails
        return {
            'statusCode': 500, 
            'body': json.dumps({
                'error': 'Database initialization failed', 
                'details': str(e)
            })
        }
    
    # Create timestamp for this scraping session
    scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Initialize data structure for aggregated results
    all_scraped_data = {
        "scrape_timestamp_utc": scraped_at.isoformat(), 
        "categories": {}
    }
    
    total_articles_scraped = 0
    total_articles_saved = 0
    
    # Process each news category with time limit monitoring
    for category_name, rss_url in NEWS_CATEGORIES.items():
        # Check remaining execution time (270s = 4.5min, leaving 30s buffer)
        if time.time() - start_time > 270:
            logger.warning("⏰ Approaching Lambda timeout, skipping remaining categories")
            break
        
        # Scrape articles from current category
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        total_articles_scraped += len(articles)
        
        # Save articles to database if any were found
        if articles:
            saved_count = save_articles_to_mysql(articles, category_name, scraped_at)
            total_articles_saved += saved_count
        
        # Brief delay to be respectful to Google's servers
        time.sleep(0.2)

    # Save backup data to S3 regardless of database operations
    try:
        # Generate timestamped filename for S3 storage
        file_name = f"google_news_{scraped_at.strftime('%Y-%m-%d_%H-%M-%S')}.json"
        
        # Upload JSON data to S3 with proper encoding
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME, 
            Key=file_name,
            Body=json.dumps(all_scraped_data, indent=2, ensure_ascii=False),
            ContentType='application/json; charset=utf-8'
        )
        logger.info(f"📦 S3 backup saved: {file_name}")
    except Exception as e:
        logger.error(f"S3 backup error: {e}")

    # Calculate execution metrics and create comprehensive summary
    elapsed_time = time.time() - start_time
    summary = (
        f"🏁 EXECUTION SUMMARY: {len(all_scraped_data['categories'])}/{len(NEWS_CATEGORIES)} categories processed. "
        f"Total {total_articles_scraped} articles scraped, {total_articles_saved} articles saved to database. "
        f"Execution time: {elapsed_time:.2f}s"
    )
    
    logger.info(summary)
    
    # Return success response with execution summary
    return {
        'statusCode': 200,
        'body': json.dumps({'message': summary}, ensure_ascii=False)
    }