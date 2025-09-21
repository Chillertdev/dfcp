# Enhanced Lambda Function - Corrected Parser + DB Performance Fix
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

# BeautifulSoup XML uyarılarını gizle
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Logging konfigürasyonu
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS S3 konfigürasyonu
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'dfcp-scraped-bucket')
s3_client = boto3.client('s3')

# RDS MySQL konfigürasyonu
RDS_HOST = os.environ.get('RDS_HOST')
RDS_USERNAME = os.environ.get('RDS_USERNAME') 
RDS_PASSWORD = os.environ.get('RDS_PASSWORD')
RDS_DATABASE = os.environ.get('RDS_DATABASE', 'news_db')
RDS_PORT = int(os.environ.get('RDS_PORT', 3306))

# Google News RSS URL'leri
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}

def get_mysql_connection():
    """MySQL veritabanına bağlantı oluşturur."""
    try:
        connection = pymysql.connect(
            host=RDS_HOST, user=RDS_USERNAME, password=RDS_PASSWORD,
            database=RDS_DATABASE, port=RDS_PORT, charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=10
        )
        logger.info("MySQL bağlantısı başarılı")
        return connection
    except Exception as e:
        logger.error(f"MySQL bağlantı hatası: {e}")
        raise

def init_database():
    """Veritabanı tablolarını oluşturur veya günceller."""
    connection = get_mysql_connection()
    try:
        with connection.cursor() as cursor:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS news_articles (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(1000) NOT NULL, url VARCHAR(1024) NOT NULL,
                short_description TEXT, source VARCHAR(255), category VARCHAR(50) NOT NULL,
                published_date DATETIME, rank_position INT, scraped_at DATETIME NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_category_scraped (category, scraped_at),
                INDEX idx_source_scraped (source, scraped_at),
                INDEX idx_rank_scraped (rank_position, scraped_at),
                UNIQUE KEY uk_url_scraped_at (url(255), scraped_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
            cursor.execute(create_table_sql)
            connection.commit()
            logger.info("Veritabanı tablosu hazırlandı veya mevcut.")
    finally:
        connection.close()

def is_within_last_hour(published_date_str):
    """Haberin yayınlanma tarihinin son 1 saat içinde olup olmadığını kontrol eder."""
    if not published_date_str: return False
    try:
        pub_date = date_parser.parse(published_date_str).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        return (now_utc - pub_date).total_seconds() <= 3600
    except Exception: return False

def extract_article_data(item):
    """RSS item'ından haber verilerini çıkarır."""
    try:
        full_title = item.find('title').get_text(strip=True)
        if ' - ' in full_title:
            title, source = full_title.rsplit(' - ', 1)
        else:
            title = full_title
            source = item.find('source').get_text(strip=True) if item.find('source') else "Bilinmiyor"
        
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
        logger.warning(f"Haber verisi çıkarılırken hata: {e}")
        return None

def scrape_category(category_name, rss_url):
    """Belirli bir haber kategorisinden haberleri çeker."""
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)'}
    try:
        logger.info(f"Kategori çekiliyor: {category_name}")
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # *** DÜZELTME: Sizin orijinal parser'ınıza geri dönüldü ***
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item')
        
        articles = []
        for index, item in enumerate(items):
            article_data = extract_article_data(item)
            if article_data and is_within_last_hour(article_data['published_date']):
                article_data['rank'] = index + 1
                articles.append(article_data)
        
        logger.info(f"✅ {category_name}: {len(articles)} haber son 1 saat içinde bulundu.")
        return articles
    except Exception as e:
        logger.error(f"❌ {category_name} kategorisi çekilirken hata: {e}")
        return []

def save_articles_to_mysql(articles, category, scraped_at):
    """Haberleri MySQL'e toplu olarak kaydeder."""
    if not articles: return 0
    connection = get_mysql_connection()
    
    insert_sql = """
    INSERT IGNORE INTO news_articles 
    (title, url, short_description, source, category, published_date, rank_position, scraped_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    values_to_insert = []
    for article in articles:
        try:
            published_datetime = date_parser.parse(article['published_date']).astimezone(timezone.utc).replace(tzinfo=None) if article['published_date'] else None
            values_to_insert.append((
                article['title'], article['url'], article.get('short_description'),
                article['source'], category, published_datetime, article.get('rank'), scraped_at
            ))
        except Exception as e:
            logger.warning(f"Veri hazırlama hatası: {article.get('title')} - {e}")

    if not values_to_insert:
        connection.close()
        return 0

    try:
        with connection.cursor() as cursor:
            result = cursor.executemany(insert_sql, values_to_insert)
            connection.commit()
            logger.info(f"💾 MySQL'e kaydedildi: {result}/{len(values_to_insert)} haber ({category})")
            return result
    except Exception as e:
        logger.error(f"MySQL toplu kaydetme hatası ({category}): {e}")
        return 0
    finally:
        connection.close()

def lambda_handler(event, context):
    """AWS Lambda ana fonksiyonu."""
    start_time = time.time()
    logger.info("🚀 Lambda başlatıldı - Düzeltilmiş Parser ve Optimize DB")

    try:
        init_database()
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': 'Veritabanı başlatma hatası', 'details': str(e)})}
    
    scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    all_scraped_data = {"scrape_timestamp_utc": scraped_at.isoformat(), "categories": {}}
    total_articles_scraped = 0
    total_articles_saved = 0
    
    for category_name, rss_url in NEWS_CATEGORIES.items():
        if time.time() - start_time > 270:
            logger.warning("⏰ Zaman sınırı yaklaştı, kalan kategoriler atlandı.")
            break
        
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        total_articles_scraped += len(articles)
        
        if articles:
            saved_count = save_articles_to_mysql(articles, category_name, scraped_at)
            total_articles_saved += saved_count
        
        time.sleep(0.2)

    try:
        file_name = f"google_news_{scraped_at.strftime('%Y-%m-%d_%H-%M-%S')}.json"
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME, Key=file_name,
            Body=json.dumps(all_scraped_data, indent=2, ensure_ascii=False),
            ContentType='application/json; charset=utf-8'
        )
        logger.info(f"📦 S3'e kaydedildi: {file_name}")
    except Exception as e:
        logger.error(f"S3'e kaydetme hatası: {e}")

    elapsed_time = time.time() - start_time
    summary = (
        f"🏁 ÖZET: {len(all_scraped_data['categories'])}/{len(NEWS_CATEGORIES)} kategori işlendi. "
        f"Toplam {total_articles_scraped} haber çekildi, {total_articles_saved} haber veritabanına eklendi. "
        f"Süre: {elapsed_time:.2f}s"
    )
    logger.info(summary)
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': summary}, ensure_ascii=False)
    }