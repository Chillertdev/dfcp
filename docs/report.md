# DFCP: AWS Lambda ile Otomatik Google News Scraper Projesi

![Project Banner](https://miro.medium.com/v2/resize:fit:828/format:webp/0*HOXAe45yHt0fLYUv.jpg)

## 🚀 Giriş

Modern veri dünyasında, güncel haber verilerinin otomatik olarak toplanması ve işlenmesi kritik bir ihtiyaç haline gelmiştir. Bu projede, **Data Fellow Crawler Project (DFCP)** adı altında, Google News sitesinden saatlik olarak haber verilerini toplayan, AWS bulut altyapısını kullanan bir sistem geliştirdim.

Bu yazıda, başlangıç seviyesi okuyucular için AWS Lambda, S3 (Simple Storage Service), EventBridge gibi servisleri kullanarak nasıl başlangıç seviye otomatik bir web scraping (web kazıma) sistemi kurduğumu adım adım anlatacağım.

## 🎯 Proje Hedefi

Projenin temel amacı:
- ✅ Google Haberler'den RSS Feed ile 6 farklı kategoriden haber verilerini toplamak
- ✅ Toplanan verileri AWS S3'te güvenli bir şekilde saklamak
- ✅ Son 1 saat içinde yayınlanan haberleri filtreleyerek güncel içeriğe odaklanmak
- ✅ Bu işlemi saatte bir otomatik olarak gerçekleştirmek(EventBridge Rule ile)

## 🏗️ Mimari

### AWS Mimarisine Genel Bakış

![AWS Architecture](https://i.hizliresim.com/luwpqe2.png)

Sistem aşağıdaki AWS bileşenlerini kullanıyor:

| Servis | Görev |
|--------|-------|
| **EventBridge** | Saatlik tetikleyici |
| **AWS Lambda** | Ana işleme fonksiyonu |
| **AWS S3** | Veri depolama |

### 🔧 Sistem Bileşenleri

#### 1. EventBridge Rule - Otomatik Tetikleme

Amazon EventBridge, lambda fonksiyonunu saatte bir kez tetikler. Aşağıdaki görselde 1 saat olarak ayarladım. 

![EventBridge Configuration](https://i.hizliresim.com/64lbrcq.jpg)

Alttaki görselde ise hangi fonksiyonu hedeflemesi ve Role ismi seçilir. (Bu projede dfcp-lambda-function adıyla Lamba fonksiyonunu seçtim.) 
![EventBridge Configuration](https://i.hizliresim.com/kvlajsj.png)

#### 2. AWS Lambda Fonksiyonu

Lambda fonksiyonumuz ana işi yapan fonksiyondur (Bu projede Google Haberler'den haber verilerini alır ve S3'e kaydeder).  Python 3.13 runtime'ı kullandım. (Siz farklı dil ve farklı versiyonları kullanabilirsin. Aws birçok seçenek sunuyor.)

**⚙️ Temel Konfigürasyon:**
- **Runtime**: Python 3.13
- **Memory**: 256 MB (Çok iş yükü olmadığı için 256 mb yeterli )
- **Timeout**: 1 dakika
- **Environment Variable**: `S3_BUCKET_NAME` = dfcp-scraped-bucket (S3'teki bucketımın adını değişkene atadım. Birçok farklı değişken tanımlayıp kod bakımını ve okunabilirliği kolaylaştırabilirsiniz.)

![Lambda Configuration](https://i.hizliresim.com/pees8ia.png)
*[Lambda Fonksiyon Konfigürasyonu Görseli]*

#### 3. S3 Bucket (Kova) - Veri Depolama

Scrape edilmiş (kazılmış) haberler JSON formatında S3 bucket'ına kaydedilir. Her kayıt doyası için kaydedilen anı belirtecek şekilde zaman damgalı (timestamp'li) olarak oluşturulur. 

**📁 Dosya Formatı:**
```
google_news_2025-01-01_18-30-17.json
```

![S3 Bucket Structure](https://i.hizliresim.com/27frare.jpg)
*[S3 Bucket'a Kaydedilen Dosyalar Görseli]*

## 💻 Kod Yapısı ve İşleyiş

### 📂 Proje Klasör Yapısı

```
dfcp-google-news-scraper/
├── README.md
├── data_fellow/
│   ├── run_lambda_handler.py
│   └── src/
│       ├── lambda_function.py
└── docs/
    ├── diagrams/
    │   ├── DFCP_flowchart.png
    │   └── aws_architecture.png
    └── report.md
```

### 🔍 Ana Fonksiyonların Açıklaması

#### 1. Kategori Scraping(Kazıma)

```python
def scrape_category(category_name, rss_url):
    
    # Google News RSS'inden belirli kategorideki haberleri çeker
    
    headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 
            'Accept': 'application/rss+xml, application/xml, text/xml',
            'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache'
        }
        # Google News RSS'ine HTTP request gönder
        response = requests.get(rss_url, headers=headers, timeout=15)
        # Eğer hata olursa HTTPError verir. 
        response.raise_for_status()
        # İçeriği BeautifulSoup'daki html.parser ile parse et
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Tüm haber itemlarını al
        items = soup.find_all('item')
        
        # Son 1 saat içindeki haberleri topla
        filtered_articles = []
        all_articles = []  # Debug için tüm haberler
        
        for index, item in enumerate(items):
            article_data = extract_article_data(item) 
            if not article_data:
                continue
                
            # Son 1 saat kontrolü yap
            if is_within_last_hour(article_data['published_date']):
                article_data['rank'] = len(filtered_articles) + 1  # Rank ekle
                filtered_articles.append(article_data) #Son bir saatteki haberleri filtered_articles'a ekle
        
        
        return filtered_articles
```


#### 2. Tarih Filtreleme

```python
# Haberin son 1 saat içinde yayınlanıp yayınlanmadığını kontrol eder
def is_within_last_hour(published_date_str):

    pub_date = date_parser.parse(published_date_str) #Yayımlanma zamanını parse'lar
    now_utc = datetime.now(timezone.utc) 
    # Yayımlanma zamanının, şu anki zamanla arasındaki saniye cinsinden farkını time_diff'e ata 
    time_diff = (now_utc - pub_date).total_seconds() 
    
    return -300 <= time_diff <= 3600  # 5 dk tolerans + 1 saat
```


#### 3. Veri Çıkarma

```python
def extract_article_data(item):

    # RSS item'ından haber verilerini structure olarak çıkartılır

    try:
        # Haber başlığını al
        title_element = item.find('title')
        if not title_element:
            return None
            
        full_title = title_element.get_text(strip=True) # Başlık verisinden sadece text olan kısmı alır
        
        # Başlık formatı genellikle "Haber Başlığı - Kaynak Adı" şeklindedir bu yüzden - kontrolü yapılır
        if ' - ' in full_title: 
            title_parts = full_title.rsplit(' - ', 1)  # Son - işaretinden böl
            title = title_parts[0].strip() # title'a ilk kısmı atar
            source = title_parts[1].strip() # source'a son kısmı atar 
        else:
            # Eğer - yoksa tüm başlık title olur, source'u ayrı etiket olarak ara
            title = full_title
            source_element = item.find('source')
            source = source_element.get_text(strip=True) if source_element else "Bilinmiyor"
        
        # Yayınlanma tarihini çıkar
        pub_date_element = item.find('pubdate')
        published_date = pub_date_element.get_text(strip=True) if pub_date_element else None
        
        # Haber URL'ini ve açıklamasını çıkar
        description_element = item.find('description')
        description_text = description_element.get_text(strip=True) if description_element else ""
        
        # Description içinde HTML var, onu da parse et
        description_html = BeautifulSoup(description_text, 'html.parser')
        link_tag = description_html.find('a')  # İlk link'i bul
        
        # URL'i önce description'daki link'ten, sonra link elementinden almaya çalış
        link_element = item.find('link')
        if link_tag and link_tag.get('href'):
            url = link_tag['href']
        elif link_element:
            url = link_element.get_text(strip=True)
        else:
            url = ""
        
        # Kısa açıklama metni
        short_description = link_tag.get_text(strip=True) if link_tag else ""
        
        return {
            'title': title,
            'url': url,
            'short_description': short_description,
            'source': source,
            'published_date': published_date
        }
```
#### 4. Ana Lambda Handler Fonksiyonu

```python
def lambda_handler(event, context):
    """
    AWS Lambda ana fonksiyonu. EventBridge tarafından tetiklenir.
    Tüm kategorilerdeki haberleri toplar ve S3'e kaydeder.
    """
    logger.info("Lambda başlatıldı")
    
    # Şu anki zamanı logla
    now_utc = datetime.now(timezone.utc)
    logger.info(f"Şu anki UTC zamanı: {now_utc}")
    
    # Ana veri yapısını hazırla
    all_scraped_data = {
        "scrape_timestamp_utc": now_utc.isoformat(), 
        "filter_criteria": "Son 1 saat içindeki haberler",
        "categories": {}
    }
    
    successful_categories = 0
    total_articles = 0
    
    # Her kategori için döngü
    for category_name, rss_url in NEWS_CATEGORIES.items():
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        
        if articles:
            successful_categories += 1
            total_articles += len(articles)
    
    # S3'e kaydet
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"google_news_{timestamp}.json"
        
        json_data = json.dumps(all_scraped_data, indent=2, ensure_ascii=False)
        
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_name,
            Body=json_data,
            ContentType='application/json; charset=utf-8'
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{total_articles} haber başarıyla kaydedildi',
                'categories': successful_categories,
                'file': file_name
            }, ensure_ascii=False)
        }
    except Exception as e:
        logger.error(f"S3 hatası: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'S3 yükleme hatası'})
        }
```

**Lambda Handler'ın İş Akışı:**

1. **🚀 Başlatma**: EventBridge'den gelen tetikleyici ile çalışmaya başlar
2. **⏰ Zaman Damgası**: İşlem başlangıç zamanını UTC'de kaydeder
3. **📊 Veri Yapısı**: Tüm kategorilerin verilerini toplayacak ana JSON yapısını oluşturur
4. **🔄 Kategori Döngüsü**: 6 kategori için teker teker `scrape_category()` fonksiyonunu çağırır
5. **📈 İstatistik**: Başarılı kategori sayısı ve toplam haber sayısını hesaplar
6. **💾 S3 Kayıt**: JSON verisini timestamp'li dosya adıyla S3'e yükler
7. **📤 Response**: HTTP response döndürür (200 başarılı, 500 hatalı)

**Handler Fonksiyonunun Kritik Özellikleri:**

- **Error Handling**: S3 hatası durumunda sistem çökmez, hata mesajı döndürür
- **Logging**: Her adımda detaylı log kaydı tutar (CloudWatch'da görünür)
- **UTF-8 Support**: Türkçe karakterleri koruyarak JSON oluşturur (`ensure_ascii=False`)
- **Timestamp**: Her dosya benzersiz isim alır (aynı anda çalışsa bile çakışmaz)
### 📰 Haber Kategorileri

Google News RSS endpoint'leri:

| Kategori | URL |
|----------|-----|
| 🌍 **Dünya** | `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr` |
| ⚽ **Spor** | `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr` |
| 💼 **İş** | `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr` |
| 💻 **Teknoloji** | `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr` |
| 🎬 **Eğlence** | `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr` |
| 🏥 **Sağlık** | `https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr` |

```python
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}
```

## ⚙️ AWS Kurulum Adımları

### 1. S3 Bucket Oluşturma


**📋 Adımlar:**
1. AWS Console → S3 servisine git
2. "Create bucket" butonuna tıkla
3. Bucket name: `dfcp-scraped-bucket`(İstediğiniz ismi verebilirsiniz) 
4. Region: Ben eu-central-1 (Frankfurt) seçtim, farklı bölge seçilebilir

### 2. Lambda Fonksiyonu Oluşturma
**📋 Adımlar:**
1. AWS Console → Lambda servisine git
2. "Create function" → "Author from scratch" seç
3. Function name: `dfcp-google-news-scraper`(İstediğiniz ismi verebilirsiniz) 
4. Runtime: Python 3.13 (Farklı dil seçenekleri mevcut)
5. Execution role: Yeni rol oluştur

### 3. Lambda Permissions (IAM Role)

Lambda fonksiyonunun S3'e yazabilmesi için gerekli izinler:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:HeadBucket"
            ],
            "Resource": [
                "arn:aws:s3:::dfcp-scraped-bucket",
                "arn:aws:s3:::dfcp-scraped-bucket/*"
            ]
        }
    ]
}
```


### 4. Lambda Layers (Kütüphane Yönetimi)

Python kütüphanelerini (requests, beautifulsoup4, python-dateutil) layer olarak eklemek:
Bilgisayarınızda herhangi bir dizinde python klasorü oluşturun ve bu projede kullanılan kütüphaneleri komut istemi üzerinden pip install ile yükleyin. Bu klasorü zipleyin. AWS Lambda servisine gidin. Layers kısmında "create a layer" butonundan hazırlamış olduğunuz python isimli zip klasorünü yükleyin. Sonra fonksiyonunuzun sayfasına gidin ve Code sekmesinin altındaki Layers bölümünden AWS'e yüklediğiniz layer'ı bu fonksiyon için seçin.

### 5. EventBridge Rule Kurulumu


**📋 Adımlar:**
1. Amazon EventBridge → Rules → Create rule
2. Name: `dfcp-hourly-trigger`
3. Rule type: Schedule
4. Schedule pattern: `rate(1 hour)`
5. Target: Lambda function
6. Function: `dfcp-google-news-scraper`

## 📊 Çıktı Veri Formatı

Lambda fonksiyonumuz şu JSON formatında veri üretiyor:

```json
{
  "scrape_timestamp_utc": "2025-09-01T14:30:15.123456+00:00",
  "filter_criteria": "Son 1 saat içindeki haberler",
  "categories": {
    "dunya": [
      {
        "title": "Örnek haber başlığı",
        "url": "https://example.com/news/123",
        "short_description": "Haber özeti...",
        "source": "Haber Kaynağı",
        "published_date": "Sun, 01 Sep 2025 14:25:00 GMT",
        "rank": 1
      }
    ],
    "spor": [...],
    "is": [...],
    "teknoloji": [...],
    "eglence": [...],
    "saglik": [...]
  }
}
```


## 📊 Monitoring ve Loglama

### CloudWatch Logs

Lambda fonksiyonumuzun detaylı logları:

```python
logger.info(f"✓ {category_name}: {article_count} haber")
logger.info(f"ÖZET: {successful_categories}/{len(NEWS_CATEGORIES)} kategori, toplam {total_articles} haber")
```


### Lambda Metrics


## 🧪 Test ve Doğrulama


### 🎯 AWS Console'dan Manuel Test

![Lambda Test Event](https://i.hizliresim.com/mxmcuyh.jpg)
*[Lambda Test Event Görseli]*
## 🔒 Güvenlik ve Best Practices

### 1. Environment Variables

Sensitive bilgileri kod içine yazmak yerine environment variable kullandım:

```python
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'dfcp-scraped-bucket')
```


### 2. Error Handling

Error handling ile sistem kararlılığını sağladım:

```python
try:
    response = requests.get(rss_url, headers=headers, timeout=15)
    response.raise_for_status()
except Exception as e:
    logger.error(f"Kategori hatası - {category_name}: {e}")
    return []
```

### 3. Rate Limiting

Google News'e aşırı yük vermemek ve Google'ın güvenlik korumasından korunmak için timeout ve uygun header'lar kullandım. 
```python
headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml',
            'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache'
        }
          # Google News RSS'ine HTTP request gönder
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
```

## 📋 Özet Bilgiler

### 🛠️ Teknik Detaylar:
- **AWS Servisleri**: Lambda, S3, EventBridge
- **Programming Language**: Python 3.13
- **Key Libraries**: requests, beautifulsoup4, boto3 (AWS içi işlemler için), python-dateutil
- **Architecture Pattern**: Serverless, Event-driven

### 📊 Proje Metrikleri:
- **Kategoriler**: 6 (dünya, spor, iş, teknoloji, eğlence, sağlık)
- **Çalışma Sıklığı**: Saatlik (24 kez/gün)
- **Kayıt Veri Formatı**: JSON
- **Ortalama Response Time**: ~20 saniye
- **Günlük Veri Boyutu**: ~1-5000 KB

### 🔧 Kullanılan Teknolojiler:

| Kategori | Teknoloji | Amaç |
|----------|-----------|------|
| **Cloud Provider** | AWS | Tüm altyapı ve servislerin barındırılması |
| **Compute** | Lambda | Sunucusuz kod çalıştırma|
| **Storage** | S3 | Haber verilerinin güvenli saklanması |
| **Scheduling** | EventBridge | Otomatik saatlik tetikleme |
| **Monitoring** | CloudWatch | Sistem logları ve performans metriklerinin izlenmesi |
| **Language** | Python 3.13 | Ana geliştirme dili ve web scraping işlemleri |
| **Web Scraping** | BeautifulSoup4 | Google News RSS XML verilerinin ayrıştırılması |
| **HTTP Client** | Requests | Google News API'lerine HTTP istekleri gönderme |
| **Date Parsing** | python-dateutil | Zaman dilimi dönüştürme ve tarih filtreleme |

## SQl (MYSQL)

## Sorgu 1: Belirli bir günde en çok haber kaydedilen kategorileri listeler.
https://i.hizliresim.com/60x1ldf.jpg

SELECT
    category,
    COUNT(*) AS article_count
FROM
    news_articles
WHERE
    -- Analiz etmek istediğiniz gün
    DATE(scraped_at) = '2025-09-11'
GROUP BY
    category
ORDER BY
    article_count DESC;

## Sorgu 2: Belirli bir günde ilk 5 sırada en çok yer alan 10 haber kaynağını listeler.
https://i.hizliresim.com/gczam5g.jpg
'2025-09-13' yerine CURDATE() yazarak sorguyu her zaman o gün için çalıştırabilirsiniz.

SELECT
    source,
    COUNT(*) AS top_rank_count
FROM
    news_articles
WHERE
    -- Analiz etmek istediğiniz gün
    DATE(scraped_at) = '2025-09-13'
    
GROUP BY
    source
ORDER BY
    top_rank_count DESC
LIMIT 10; -- En çok çıkan ilk 10 kaynağı gösterir
---

## Sorgu 3: Belirli bir günün belirli bir saatinde birden fazla haber yayınlayan kaynakları listeler.
https://i.hizliresim.com/lqtwe5s.jpg
-- HOUR(scraped_at) = 14; -> Saat 14:00 ile 14:59 arasını ifade eder.

SELECT
    source,
    COUNT(*) AS repetition_count
FROM
    news_articles
WHERE
    -- Analiz etmek istediğiniz gün
    DATE(scraped_at) = '2025-09-13'
    
    -- Analiz etmek istediğiniz saat (0-23 arası)
    AND HOUR(scraped_at) = 10
GROUP BY
    source
HAVING
    repetition_count > 1 
ORDER BY
    repetition_count DESC;
### 📞 İletişim ve Kaynak Kodları

- **GitHub Repository**: [DFCP Google News Scraper](https://github.com/Chillertdev/dfcp)
