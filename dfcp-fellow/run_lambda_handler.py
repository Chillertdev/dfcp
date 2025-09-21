import json
import boto3
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone
import logging
import os
import warnings
from dateutil import parser as date_parser
import time

# BeautifulSoup XML uyarılarını gizle
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Logging konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# AWS S3 konfigürasyonu
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'dfcp-scraped-bucket')

# Google News RSS URL'leri
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}

def initialize_s3_client():
    """S3 client'ı başlatır."""
    try:
        # AWS credentials otomatik olarak ~/.aws/credentials dosyasından veya environment variables'dan alınır
        s3_client = boto3.client('s3')
        logger.info("S3 client başarıyla başlatıldı")
        return s3_client
    except Exception as e:
        logger.error(f"S3 client başlatma hatası: {e}")
        logger.error("AWS credentials'ınızın doğru şekilde yapılandırıldığından emin olun")
        raise

def is_within_last_hour(published_date_str):
    """Haberin yayınlanma tarihinin son 1 saat içinde olup olmadığını kontrol eder."""
    if not published_date_str: 
        return False
    try:
        pub_date = date_parser.parse(published_date_str).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        time_diff = (now_utc - pub_date).total_seconds()
        return time_diff <= 3600
    except Exception as e:
        logger.warning(f"Tarih parse hatası: {e}")
        return False

def extract_article_data(item):
    """RSS item'ından haber verilerini çıkarır."""
    try:
        title_element = item.find('title')
        if not title_element:
            return None
            
        full_title = title_element.get_text(strip=True)
        
        # Title ve source'u ayır
        if ' - ' in full_title:
            title, source = full_title.rsplit(' - ', 1)
        else:
            title = full_title
            source_element = item.find('source')
            source = source_element.get_text(strip=True) if source_element else "Bilinmiyor"
        
        # Description'dan URL çıkar
        description_element = item.find('description')
        url = ""
        short_description = ""
        
        if description_element:
            description_html = BeautifulSoup(description_element.get_text(strip=True), 'html.parser')
            link_tag = description_html.find('a')
            if link_tag:
                url = link_tag.get('href', '')
                short_description = link_tag.get_text(strip=True)
        
        # Eğer description'dan URL alınamazsa, link tag'inden al
        if not url:
            link_element = item.find('link')
            url = link_element.get_text(strip=True) if link_element else ""
        
        # Published date
        pubdate_element = item.find('pubdate')
        published_date = pubdate_element.get_text(strip=True) if pubdate_element else None

        return {
            'title': title.strip(),
            'url': url,
            'short_description': short_description,
            'source': source.strip(),
            'published_date': published_date
        }
    except Exception as e:
        logger.warning(f"Haber verisi çıkarılırken hata: {e}")
        return None

def scrape_category(category_name, rss_url):
    """Belirli bir haber kategorisinden haberleri çeker."""
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)'}
    try:
        logger.info(f"Kategori çekiliyor: {category_name}")
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item')
        
        articles = []
        for index, item in enumerate(items):
            article_data = extract_article_data(item)
            if article_data and is_within_last_hour(article_data['published_date']):
                article_data['rank'] = index + 1
                articles.append(article_data)
        
        logger.info(f"✅ {category_name}: {len(articles)} haber son 1 saat içinde bulundu (Toplam: {len(items)})")
        return articles
    except requests.RequestException as e:
        logger.error(f"❌ {category_name} kategorisi çekilirken network hatası: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ {category_name} kategorisi çekilirken hata: {e}")
        return []

def save_to_s3(data, s3_client, scraped_at):
    """Veriyi S3'e kaydeder."""
    try:
        file_name = f"google_news_{scraped_at.strftime('%Y-%m-%d_%H-%M-%S')}.json"
        
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_name,
            Body=json.dumps(data, indent=2, ensure_ascii=False),
            ContentType='application/json; charset=utf-8'
        )
        logger.info(f"📦 S3'e kaydedildi: s3://{S3_BUCKET_NAME}/{file_name}")
        return True
    except Exception as e:
        logger.error(f"❌ S3'e kaydetme hatası: {e}")
        return False

def save_to_local_file(data, scraped_at):
    """Backup olarak local file'a da kaydet."""
    try:
        os.makedirs('scraped_data', exist_ok=True)
        file_name = f"scraped_data/google_news_{scraped_at.strftime('%Y-%m-%d_%H-%M-%S')}.json"
        
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Lokal dosyaya kaydedildi: {file_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Lokal dosyaya kaydetme hatası: {e}")
        return False

def main():
    """Ana fonksiyon - lokal çalıştırma için."""
    start_time = time.time()
    logger.info("🚀 Lokal News Scraper başlatıldı")

    try:
        s3_client = initialize_s3_client()
    except Exception as e:
        logger.error("S3 client başlatılamadı, sadece lokal kaydetme yapılacak")
        s3_client = None
    
    scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    all_scraped_data = {
        "scrape_timestamp_utc": scraped_at.isoformat(),
        "scraper_version": "local_v1.0",
        "categories": {}
    }
    
    total_articles_scraped = 0
    
    for category_name, rss_url in NEWS_CATEGORIES.items():
        logger.info(f"\n--- {category_name.upper()} kategorisi işleniyor ---")
        
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = {
            "article_count": len(articles),
            "articles": articles
        }
        total_articles_scraped += len(articles)
        
        # Rate limiting
        time.sleep(1)
    
    # Sonuçları kaydet
    logger.info(f"\n{'='*50}")
    logger.info("📊 SCRAPING TAMAMLANDI - Kaydetme işlemleri başlıyor")
    
    # S3'e kaydet
    if s3_client:
        save_to_s3(all_scraped_data, s3_client, scraped_at)
    
    # Lokal backup
    save_to_local_file(all_scraped_data, scraped_at)
    
    elapsed_time = time.time() - start_time
    summary = (
        f"\n🏁 ÖZET RAPOR:\n"
        f"   • İşlenen kategori sayısı: {len(all_scraped_data['categories'])}/{len(NEWS_CATEGORIES)}\n"
        f"   • Toplam çekilen haber: {total_articles_scraped}\n"
        f"   • Toplam süre: {elapsed_time:.2f} saniye\n"
        f"   • S3 bucket: {S3_BUCKET_NAME}\n"
        f"   • Scraping zamanı: {scraped_at.isoformat()}"
    )
    logger.info(summary)
    
    return all_scraped_data

if __name__ == "__main__":
    try:
        result = main()
        print("\n✅ Scraping işlemi başarıyla tamamlandı!")
    except KeyboardInterrupt:
        print("\n⏹️  İşlem kullanıcı tarafından durduruldu")
    except Exception as e:
        logger.error(f"\n❌ Fatal hata: {e}")
        print(f"❌ Hata: {e}")