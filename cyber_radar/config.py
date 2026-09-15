"""Merkezi konfigürasyon. .env dosyasını okur, her modül buradan import eder."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _list_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://cyber_radar:CHANGE_ME@localhost:5432/cyber_radar")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Ucuz/hızlı katman (relevance filtresi). Bu isim, https://ai.google.dev/gemini-api/docs/models
# sayfasına ve gerçek bir API çağrısına karşı 2026-09-07'de teyit edildi (ücretsiz
# katmanda çalışıyor). gemini-3.7-flash bir önceki nesil oldu (hâlâ çalışıyor ama
# artık "previous-generation" işaretli); flagship flash şu an 3.8. Google'ın model
# adları zaman zaman kapatılıyor (2.0 flash, 3.1 flash-lite preview, 3 pro preview
# gibi) - periyodik olarak yukarıdaki sayfadan teyit edip gerekirse .env içinde
# RELEVANCE_MODEL/ANALYSIS_MODEL'i güncelleyin; buradaki varsayılan bilinçli olarak
# SABİT tutuluyor, otomatik "en yeni model" seçimi yapılmıyor.
RELEVANCE_MODEL = os.getenv("RELEVANCE_MODEL", "gemini-3.8-flash")
# Derin analiz katmanı. Bilinçli olarak burada da (pro yerine) flash varsayılan
# bırakıldı ki ücretsiz katmanda kutudan çıktığı gibi çalışsın; daha güçlü akıl
# yürütme istiyorsanız güncel pro model adını yukarıdaki sayfadan kontrol edip
# .env içinde ANALYSIS_MODEL'i değiştirin (pro modelleri genelde ücretsiz
# katmanda çok daha kısıtlı kotayla gelir).
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "gemini-3.8-flash")

# --- Gemini kota/tempo (load balancing) ---
# Bir koşuda toplanan 'pending' haber/makale sayısı sınırsız büyüyebilir (ör.
# 30 günlük historical scan sonrası) - relevance + derin analiz döngüleri
# hiçbir sınır koymadan art arda çağırırsa, ücretsiz tier'ın hem dakikalık
# (RPM) hem günlük (RPD) limitini TEK KOŞUDA aşabilir. GERÇEK limit CANLI
# doğrulandı (2026-09-10, gemini-3.8-flash, 429 RESOURCE_EXHAUSTED gövdesi):
# "generate_content_free_tier_requests ... quotaValue: 20" - yani hesabın
# GERÇEK günlük hakkı 20 istek. Varsayılan bilinçli olarak bunun ALTINDA
# tutuluyor (pay bırakır) - .env'de GEMINI_DAILY_REQUEST_LIMIT açıkça set
# edilmemişse burası artık 18 (eski varsayılan 190 gerçek kotayla HİÇ
# uyuşmuyordu - .env'siz bir kurulumda ilk koşuda garanti 429/çökme
# üretirdi, bkz. proje notları kök neden analizi).
GEMINI_DAILY_REQUEST_LIMIT = int(os.getenv("GEMINI_DAILY_REQUEST_LIMIT", "18"))
# cyber-radar.timer günde kaç kez çalışıyorsa o (bkz. systemd/cyber-radar.timer,
# varsayılan 07:30/19:30 = 2 koşu). Günlük hak buna bölünüp koşular arasında
# eşit paylaştırılır ki sabah koşusu günün tüm kotasını tüketip akşam koşusunu
# aç bırakmasın.
GEMINI_RUNS_PER_DAY = int(os.getenv("GEMINI_RUNS_PER_DAY", "2"))
# İki LLM çağrısı arasında minimum bekleme (saniye) - dakikalık (RPM) limitine
# karşı; bir koşu içindeki ani patlamaları (burst) yavaşlatır.
GEMINI_MIN_CALL_INTERVAL_SECONDS = float(os.getenv("GEMINI_MIN_CALL_INTERVAL_SECONDS", "2.0"))

# 2026-09-13: recovery backfill (bkz. src/recovery/) çok sayıda profil/
# sorgu kombinasyonunu art arda tarayabildiği için akademik kaynak
# çağrıları arasına eklenen bekleme - SADECE run_type != 'incremental'
# iken uygulanır (bkz. run_pipeline._collect_profile), normal günlük
# koşuyu HİÇ ETKİLEMEZ. Canlı pilotta arXiv (en sıkı limitli kaynak)
# bu olmadan 20 sorgunun 19'unda 429 verdi.
RECOVERY_INTER_CALL_DELAY_SECONDS = float(os.getenv("RECOVERY_INTER_CALL_DELAY_SECONDS", "3.0"))

# --- Operasyonel istihbarat (haber) vs akademik makale: BAĞIMSIZ LLM bütçesi
# (2026-09-10 kök neden analizi) ---
# ESKİ davranış: tek bir paylaşılan LLMBudget, hem haber hem makale
# relevance/derin-analiz döngülerini besliyordu VE makaleler döngülerde HER
# ZAMAN haberlerden ÖNCE işleniyordu (bkz. run_pipeline.main() sırası). Bu
# ikisi birleşince: araştırma profilleri (research profile A/B slotları) makale
# hacmini büyüttükçe paylaşılan günlük bütçe makalelerde tükeniyor, haber
# relevance/derin-analiz döngüleri SIFIR pay bulup hiç çalışmıyordu ->
# analyzed_news=[] -> digest.generate_brief'e giden haber listesi boş ->
# 🚨/🕵️/📚/👀 dörtlüsünün TAMAMI "bu dönemde ... yok" yazıyordu (makaleler
# ise KENDİ backfill/rotasyon havuzundan - bkz. _select_current_papers/
# _select_historical_highlights - besleniyordu, o yüzden makale bölümleri
# hep doluydu). Canlı log kanıtı: 2026-09-10 19:31 koşusu, tam bu senaryo.
#
# YENİ davranış: haber ve makale artık İKİ BAĞIMSIZ günlük havuz kullanıyor
# (src.llm.budget.NamedBudget, pool="ops_news"/"ops_papers") - biri
# tükenmesi diğerini ETKİLEMEZ. İkisinin toplamı GEMINI_DAILY_REQUEST_LIMIT'i
# (gerçek hesap kotası) AŞMAMALI - varsayılanlar buna göre temkinli seçildi.
NEWS_DAILY_LLM_BUDGET = int(os.getenv("NEWS_DAILY_LLM_BUDGET", "9"))
PAPERS_DAILY_LLM_BUDGET = int(os.getenv("PAPERS_DAILY_LLM_BUDGET", "9"))

CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

KEYWORDS = _list_env("KEYWORDS", "cybersecurity")
NEWS_FEEDS = _list_env("NEWS_FEEDS", "")

# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md C2): "Aksiyon
# Gerekli" önceliklendirmesinde ek ağırlık verilecek yüksek-değerli vendor/
# ürün/sistem listesi - bkz. src/llm/news_analyst.compute_priority(). Bu
# ürünlerden biri bir haberin vendors/products alanında geçiyorsa (case-
# insensitive) küçük bir bonus puan eklenir - kurumsal ortamda en yaygın/
# kritik sistemler (config-driven, kod değişikliği gerektirmeden
# genişletilebilir).
HIGH_VALUE_VENDOR_KEYWORDS = _list_env(
    "HIGH_VALUE_VENDOR_KEYWORDS",
    "Microsoft,Windows,Active Directory,Linux,Cisco,Fortinet,Palo Alto,Ivanti,"
    "Citrix,VMware,Splunk,Elastic,Wazuh,SIEM,EDR,XDR,VPN,Firewall,WAF,Identity",
)

# --- V1.1 research profiles (bkz. src/research/profiles.py) ---
# Hangi profiles/<id>.yaml dosyalarının HER pipeline koşusunda aktif
# olacağı, sırayla. Varsayılan "daily_cyber" TEK BAŞINA - mevcut KEYWORDS
# davranışını birebir korur, profile sistemine geçiş default'ta davranış
# değiştirmez. Research Profile A/B taramasını açmak için ör.
# ACTIVE_RESEARCH_PROFILES=daily_cyber,soc_analyst,security_researcher
ACTIVE_RESEARCH_PROFILES = _list_env("ACTIVE_RESEARCH_PROFILES", "daily_cyber")

# Credential gerektiren (ücretli/kurumsal) akademik kaynaklar: BİLİNÇLİ
# OLARAK henüz collector'ları YAZILMADI (bkz. proje notları: "sahte sonuç
# üretme, canlı çalışıyormuş gibi işaretleme"). Key'i olmayanlar için
# _collect_profile() her koşuda collector_runs'a 'disabled_missing_credentials'
# yazar ki coverage raporunda "bu kaynak neden 0 katkı yaptı" sorusu
# "hiç sorgulanmadı, key yok" ile "sorguladık, sonuç yok" birbirinden
# ayrılsın. Key eklenince (ör. IEEE_XPLORE_API_KEY=...) BURADAKİ isim/env
# eşlemesi değişmeden kalır - gerçek collector'ı kim yazarsa bu sözlüğe
# dokunmasına gerek yok, sadece kendi search() fonksiyonunu _collect_profile'a
# bağlaması yeterli.
OPTIONAL_ACADEMIC_SOURCES = {
    "ieee_xplore": "IEEE_XPLORE_API_KEY",
    "scopus": "SCOPUS_API_KEY",
    "web_of_science": "WOS_API_KEY",
    "lens": "LENS_API_KEY",
    "springer_nature": "SPRINGER_API_KEY",
    "core": "CORE_API_KEY",
    "serpapi_scholar": "SERPAPI_API_KEY",
    "scrapebadger_scholar": "SCRAPEBADGER_API_KEY",
    "serply_scholar": "SERPLY_API_KEY",
}

# DBLP: key GEREKMİYOR ama production host'tan bile bot-korumasına takıldığı
# doğrulandı (bkz. docs/ACCEPTANCE_DEBT.md ACCEPTANCE-02 - "degraded_optional",
# credential eksikliğinden FARKLI bir kategori). Varsayılan KAPALI - her
# koşuda boşuna tekrar tekrar denenmesin. Erişim düzelirse true yapılabilir.
DBLP_ENABLED = os.getenv("DBLP_ENABLED", "false").strip().lower() == "true"

# NOTE: the systematic-review workflow (screening/evidence-matrix/gap-
# analysis, with its own DAILY_SCREENING_BUDGET/RESEARCH_ANALYSIS_BUDGET
# pools) is not part of this public product - see docs/ARCHITECTURE.md
# "Not included". Research Profile A/B (below) reuses the ops_papers/
# per-profile LLM budgets instead.

CISA_KEV_URL = os.getenv(
    "CISA_KEV_URL",
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
)

RELEVANCE_THRESHOLD_HIGH = float(os.getenv("RELEVANCE_THRESHOLD_HIGH", "0.75"))
RELEVANCE_THRESHOLD_LOW = float(os.getenv("RELEVANCE_THRESHOLD_LOW", "0.4"))

# --- Brifing kota hedefleri (config-driven, hard-code YOK - proje notları) ---
# Operasyonel (haber) kategorileri: 🚨 Aksiyon Gerekli / 🕵️ Hunt Fırsatı /
# 📚 Öğretici / 👀 Farkındalık - HER BİRİ için HEDEF (zorunlu taban DEĞİL,
# bkz. _select_news_for_digest: sırf doldurmak için düşük kaliteli/alakasız
# haber EKLENMEZ, sadece gerçekten o tier'a ait, daha önce analiz edilmiş
# ama henüz gösterilmemiş haberlerle tamamlanır).
# OPERATIONAL_CATEGORY_TARGET tek başına HER 4 kategoriye eşit uygulanan
# eski/legacy varsayılan - PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md
# A2/Y1) 4 kategoriyi BAĞIMSIZ config'e ayırdı ki biri diğerinden farklı
# ayarlanabilsin (ör. Hunt hedefi 3'e düşürülüp Action 7'ye çıkarılabilir).
# Her biri ayrı env var'ı VERİLMEMİŞSE OPERATIONAL_CATEGORY_TARGET'a düşer -
# mevcut .env'ler (sadece OPERATIONAL_CATEGORY_TARGET set edenler) davranış
# değişikliği YAŞAMAZ.
OPERATIONAL_CATEGORY_TARGET = int(os.getenv("OPERATIONAL_CATEGORY_TARGET", "5"))
OPERATIONAL_ACTION_TARGET = int(os.getenv("OPERATIONAL_ACTION_TARGET", str(OPERATIONAL_CATEGORY_TARGET)))
OPERATIONAL_HUNT_TARGET = int(os.getenv("OPERATIONAL_HUNT_TARGET", str(OPERATIONAL_CATEGORY_TARGET)))
OPERATIONAL_TUTORIAL_TARGET = int(os.getenv("OPERATIONAL_TUTORIAL_TARGET", str(OPERATIONAL_CATEGORY_TARGET)))
OPERATIONAL_AWARENESS_TARGET = int(os.getenv("OPERATIONAL_AWARENESS_TARGET", str(OPERATIONAL_CATEGORY_TARGET)))
# Akademik kategoriler - bkz. run_pipeline._select_current_papers/
# _select_learning_path/_select_historical_highlights.
ACADEMIC_CURRENT_TARGET = int(os.getenv("ACADEMIC_CURRENT_TARGET", "5"))       # 🆕 Güncel Makale
ACADEMIC_TIMELINE_TARGET = int(os.getenv("ACADEMIC_TIMELINE_TARGET", "5"))     # 🧭 Temelden Güncele
ACADEMIC_CLASSIC_TARGET = int(os.getenv("ACADEMIC_CLASSIC_TARGET", "1"))       # 🏛️ Bugünün Klasiği
ACADEMIC_HISTORICAL_TARGET = int(os.getenv("ACADEMIC_HISTORICAL_TARGET", "5")) # 📚 Geçmişten Öne Çıkanlar

# --- Research Profile A/B digest bridge (GENERIC, public export) ---
# İki OPSİYONEL "kendi ayrı digest bölümü olan" araştırma profili slotu -
# bkz. docs/PROFILES.md. Varsayılan boş = özellik tamamen kapalı (hiçbir
# profil bu slotlara atanmadıysa run_pipeline bu adımı hiç çalıştırmaz).
# Kota: DİĞER akademik kategorilerden TAMAMEN BAĞIMSIZ ("bir kategorinin
# bütçesi veya result sayısı diğerini etkilemesin").
RESEARCH_PROFILE_A_ID = os.getenv("RESEARCH_PROFILE_A_ID", "").strip()
RESEARCH_PROFILE_B_ID = os.getenv("RESEARCH_PROFILE_B_ID", "").strip()
RESEARCH_PROFILE_A_TARGET = int(os.getenv("RESEARCH_PROFILE_A_TARGET", "5"))
RESEARCH_PROFILE_B_TARGET = int(os.getenv("RESEARCH_PROFILE_B_TARGET", "5"))
# LLM bütçesi de AYRI havuz - ops_news/ops_papers'ı YEMEZ, onlar da bunu
# yemez. Varsayılan düşük tutuldu, bu "bonus zenginleştirme" ana haber/
# makale hattının önüne geçmemeli.
RESEARCH_PROFILE_A_LLM_BUDGET = int(os.getenv("RESEARCH_PROFILE_A_LLM_BUDGET", "3"))
RESEARCH_PROFILE_B_LLM_BUDGET = int(os.getenv("RESEARCH_PROFILE_B_LLM_BUDGET", "3"))
# Bir profilin extraction_schema'sındaki digest-bridge alan adları -
# bkz. profiles/examples/*.yaml. Varsayılanlar örnek profillerle eşleşir;
# kendi profilinizi farklı alan adlarıyla yazarsanız burayı güncelleyin.
RESEARCH_PROFILE_A_SCORE_FIELD = os.getenv("RESEARCH_PROFILE_A_SCORE_FIELD", "relevance_score")
RESEARCH_PROFILE_A_REASON_FIELD = os.getenv("RESEARCH_PROFILE_A_REASON_FIELD", "why_relevant")
RESEARCH_PROFILE_A_DIMS_FIELD = os.getenv("RESEARCH_PROFILE_A_DIMS_FIELD", "relevance_dimensions")
RESEARCH_PROFILE_B_SCORE_FIELD = os.getenv("RESEARCH_PROFILE_B_SCORE_FIELD", "relevance_score")
RESEARCH_PROFILE_B_REASON_FIELD = os.getenv("RESEARCH_PROFILE_B_REASON_FIELD", "why_relevant")
RESEARCH_PROFILE_B_DIMS_FIELD = os.getenv("RESEARCH_PROFILE_B_DIMS_FIELD", "relevance_dimensions")

# --- Collector health / source anomaly detection (Phase 2, madde 7-8) ---
# Toplam sonuç sayısı düşüşü (_coverage_warning, mevcut/dokunulmadı: %70+
# düşüşte uyarır) YETERSİZ - bir kaynak tamamen bozulup diğerleri onu
# telafi edebilir, toplamda fark GÖRÜNMEZ. Bu yüzden AYRICA kaynak bazlı
# karşılaştırma (bkz. run_pipeline._source_anomaly_warnings): önceki
# başarılı koşuya göre TEK bir kaynağın sonuç sayısı bu oranın ÜSTÜNDE
# düşerse (0.4 = %40 düşüş) uyarı üretir - "source X previous=320
# current=0" gibi anomalileri toplam sayıdan daha erken yakalar.
SOURCE_ANOMALY_DROP_THRESHOLD = float(os.getenv("SOURCE_ANOMALY_DROP_THRESHOLD", "0.4"))
# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md S2): tek bir koşuda
# "0 sonuç ama hata yok" tek başına kesin arıza sinyali değildir (dar
# since_date penceresi gibi zararsız nedenleri olabilir - bkz. yukarıdaki
# not). Ama AYNI kaynak ART ARDA bu kadar (veya daha fazla) incremental
# koşuda 0 sonuç veriyorsa, bu artık "izlenmeli" değil, öne çıkarılması
# gereken bir sinyaldir.
SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT = int(os.getenv("SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT", "3"))
# 2026-09-11: iki koşu normal 12 saatlik kadanstan ÇOK daha yakın zamanda
# art arda çalışırsa (ör. manuel bir tetikleme) - kaynak bazlı düşüş/toplam
# düşüş karşılaştırması YANILTICI olur (rate-limiting/dar since_date
# penceresi normal, "kaynak bozuldu" DEĞİL). Bu durumda anomaly kontrolü
# ATLANIR - bkz. proje notları: "muhtemelen bozuldu" diye YANLIŞ pozitif
# üretmesin, sadece gerçek bozulmalarda konuşsun.
ANOMALY_MIN_RUN_GAP_HOURS = float(os.getenv("ANOMALY_MIN_RUN_GAP_HOURS", "6"))

NOTEBOOKLM_PDF_VALUE_THRESHOLD = int(os.getenv("NOTEBOOKLM_PDF_VALUE_THRESHOLD", "14"))

# ---------------------------------------------------------------------------
# Google Drive senkron + yerel disk temizliği. Disk alanı sınırlı olduğu için
# tüm üretilen dosyalar (brifingler, NotebookLM markdown'ları, akademik PDF
# önbelleği) Drive'a yüklenip belirli bir süre sonra sunucudan silinir.
# GDRIVE_ENABLED=false iken hiçbir şey silinmez - retention.py sadece Drive'a
# başarıyla yüklediği dosyaları siler, asla "yükle-yoksay-sil" yapmaz.
# ---------------------------------------------------------------------------
GDRIVE_ENABLED = os.getenv("GDRIVE_ENABLED", "false").strip().lower() == "true"
GDRIVE_OAUTH_CLIENT_ID = os.getenv("GDRIVE_OAUTH_CLIENT_ID", "")
GDRIVE_OAUTH_CLIENT_SECRET = os.getenv("GDRIVE_OAUTH_CLIENT_SECRET", "")
GDRIVE_ROOT_FOLDER_ID = os.getenv("GDRIVE_ROOT_FOLDER_ID", "")
GDRIVE_ROOT_FOLDER_NAME = os.getenv("GDRIVE_ROOT_FOLDER_NAME", "Cyber Radar")

# --- Drive Queue V1 (2026-09-15) ------------------------------------------
# GDRIVE_SYNC_MODE='direct' (varsayılan): eski davranış BİREBİR korunur -
# run_pipeline.main() sonunda retention.sync_and_cleanup() senkron/doğrudan
# çalışır (bkz. docs/GOOGLE_DRIVE.md "Current"). 'queued': ana pipeline
# sadece üretilen dosyaları kalıcı kuyruğa ekler (hızlı, ağ YOK) - gerçek
# yükleme ayrı, cyber-radar-drive-sync.timer (03:30) tarafından tetiklenen
# bir worker'da, günlük bütçe dahilinde olur (bkz. src/drive_queue.py).
# Varsayılan 'direct' kalır ki bu değişiklik hiçbir mevcut davranışı
# sessizce bozmasın - 'queued'a geçiş bilinçli bir .env değişikliği ister.
GDRIVE_SYNC_MODE = os.getenv("GDRIVE_SYNC_MODE", "direct").strip().lower()
GDRIVE_DAILY_UPLOAD_BUDGET_GB = float(os.getenv("GDRIVE_DAILY_UPLOAD_BUDGET_GB", "5"))
GDRIVE_DAILY_FILE_LIMIT = int(os.getenv("GDRIVE_DAILY_FILE_LIMIT", "500"))
GDRIVE_WORKER_MAX_RUNTIME_MINUTES = int(os.getenv("GDRIVE_WORKER_MAX_RUNTIME_MINUTES", "60"))
GDRIVE_RESUMABLE_THRESHOLD_MB = float(os.getenv("GDRIVE_RESUMABLE_THRESHOLD_MB", "5"))
GDRIVE_UPLOAD_CHUNK_MB = float(os.getenv("GDRIVE_UPLOAD_CHUNK_MB", "8"))
GDRIVE_MAX_RETRIES_PER_FILE = int(os.getenv("GDRIVE_MAX_RETRIES_PER_FILE", "5"))
# Doğrulama SADECE remote size==local size + trashed==false ile YETİNMEZ,
# md5Checksum varsa onu da karşılaştırır - ama çok büyük bir dosyada yerel
# MD5 hesaplamak (tüm dosyayı okumak) maliyetli olabilir, bu yüzden bir
# tavan var (bkz. proje notları: "büyük dosyalarda local MD5 maliyetini
# göz önüne al, config ile aç/kapat").
GDRIVE_VERIFY_MD5_MAX_MB = float(os.getenv("GDRIVE_VERIFY_MD5_MAX_MB", "200"))
# data/ altında - .gitignore zaten data/'yi kapsıyor, ayrıca burada da
# credentials*.json/token*.json gibi kendi satırı YOK çünkü bu dosya secret
# İÇERMEZ (bkz. src/drive_queue.py docstring'i - session URI hassas kabul
# edilir ama state dosyasının KENDİSİ token/secret değildir, yine de 0600
# ve radar sahipliğinde tutulur).
GDRIVE_QUEUE_STATE_FILE = os.getenv(
    "GDRIVE_QUEUE_STATE_FILE", os.path.join("data", "state", "gdrive_upload_state.json")
)
# Kuyruk'un dosya taramasına/upload'a izin verdiği KÖK dizinler (exfiltration
# guard - bkz. proje notları: "queue yalnız explicitly allowed roots
# altındaki dosyaları upload edebilir"). Göreli yollar BASE_DIR'e göre
# çözülür (bkz. aşağıda).
GDRIVE_ALLOWED_ROOTS = [
    os.path.join("data", "reports"),      # includes data/reports/recovery/ (priority 10)
    os.path.join("data", "notebooklm"),
    os.path.join("data", "db_backups"),
    os.path.join("data", "research"),     # SCI/thesis evidence matrix, gap analysis, etc.
    os.path.join("data", "academic", "pdf"),
]
# notebooklm HARİÇ - "sadece kapanmış periyot" iş kuralı var (bkz.
# src/retention.py _enqueue_notebooklm), blind bir dizin taraması bunu
# ihlal eder. notebooklm yine de GDRIVE_ALLOWED_ROOTS'ta kalır (exfiltration
# guard'ı geçebilsin diye) - sadece drive_queue.scan_allowed_roots()'un
# BLIND taradığı köklerden çıkarılır.
GDRIVE_BLIND_SCAN_ROOTS = [r for r in GDRIVE_ALLOWED_ROOTS if os.path.basename(r) != "notebooklm"]

LOCAL_RETENTION_DAYS = int(os.getenv("LOCAL_RETENTION_DAYS", "2"))
# Ham PDF önbelleği (data/academic/pdf/*) için AYRI, daha kısa bekleme -
# LOCAL_RETENTION_DAYS'ten bilinçli olarak farklı: bu dosyalar sadece metin
# çıkarımı (full_text) ve -varsa- notebooklm değerli-PDF kopyası için var,
# ikisi de aynı koşu içinde biter (bkz. run_pipeline.main() sırası:
# _analyze_relevant_papers -> _export_to_notebooklm -> retention.sync_and_cleanup);
# rapor/notebooklm markdown'ları gibi 2 gün beklemesine gerek yok, gereksiz
# yere disk tutar. 0 = yaşına bakmadan HER koşuda Drive'a yükleyip sil (0'dan
# büyük bir değer verirseniz normal LOCAL_RETENTION_DAYS gibi mtime'a göre bekler).
PDF_CACHE_RETENTION_DAYS = int(os.getenv("PDF_CACHE_RETENTION_DAYS", "0"))
NOTEBOOKLM_PERIOD_DAYS = int(os.getenv("NOTEBOOKLM_PERIOD_DAYS", "2"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_PROFILES_DIR = os.getenv("RESEARCH_PROFILES_DIR", os.path.join(BASE_DIR, "profiles"))
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DIR = os.path.join(DATA_DIR, "academic", "pdf")
NOTEBOOKLM_DIR = os.path.join(DATA_DIR, "notebooklm")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
NOTEBOOKLM_INDEX_DIR = os.path.join(NOTEBOOKLM_DIR, "_index")
NOTEBOOKLM_MANIFEST_FILE = os.path.join(NOTEBOOKLM_INDEX_DIR, "collected_papers.json")
GDRIVE_TOKEN_FILE = os.path.join(DATA_DIR, ".gdrive_token.json")

# GDRIVE_QUEUE_STATE_FILE/GDRIVE_ALLOWED_ROOTS yukarıda .env'den (göreli ya
# da mutlak olabilir) okundu - burada BASE_DIR'e göre mutlak hale getiriliyor
# (DATA_DIR gibi diğer yol sabitleriyle AYNI desen).
GDRIVE_QUEUE_STATE_FILE_ABS = (
    GDRIVE_QUEUE_STATE_FILE if os.path.isabs(GDRIVE_QUEUE_STATE_FILE)
    else os.path.join(BASE_DIR, GDRIVE_QUEUE_STATE_FILE)
)
GDRIVE_ALLOWED_ROOTS_ABS = [
    root if os.path.isabs(root) else os.path.join(BASE_DIR, root)
    for root in GDRIVE_ALLOWED_ROOTS
]
GDRIVE_BLIND_SCAN_ROOTS_ABS = [
    root if os.path.isabs(root) else os.path.join(BASE_DIR, root)
    for root in GDRIVE_BLIND_SCAN_ROOTS
]

# --- Kaynak sağlık doğrulaması (2026-09-11, kullanıcı isteği: "sorun X
# görünüyor mesela, gerçekten problem varsa bunu bulsun, error loglarına
# yazsın") ---
# KÖK NEDEN (canlı teşhis edildi): _source_anomaly_warnings bir kaynağın
# sonuç sayısı düştüğünde HER ZAMAN "muhtemelen bozuldu" diyordu - ama
# collector_runs.error alanı NULL ise (gerçek bir istisna/HTTP hatası
# YOKSA) bu aslında "az/sıfır ama BAŞARILI yanıt" demektir (ör. aynı günü
# art arda taramak, dar since_date penceresi) - GERÇEK bir arıza değil.
# Artık iki seviye ayrılıyor: collector_runs.error DOLU olan kaynaklar
# "🔴 GERÇEK HATA" olarak işaretlenip AYRICA bu log dosyasına yazılıyor;
# error NULL olup sadece sayısı düşenler artık "muhtemelen bozuldu"
# DENMİYOR, daha temkinli "sonuç azaldı, hata yok, kesin arıza sinyali
# DEĞİL" ifadesiyle raporlanıyor (bkz. run_pipeline._source_anomaly_warnings).
COLLECTOR_ERROR_LOG_ENABLED = os.getenv("COLLECTOR_ERROR_LOG_ENABLED", "true").strip().lower() == "true"
COLLECTOR_ERROR_LOG_FILE = os.path.join(DATA_DIR, "logs", "collector_errors.log")

# NotebookLM'e giden konu klasörleri: kaynak dokümandaki (bölüm 30) notebook fikriyle
# birebir eşleşir. Analiz agent'ının döndürdüğü primary_domain metni buradaki
# anahtar kelimelerden biriyle eşleşirse ilgili konuya, yoksa "General" a düşer.
NOTEBOOKLM_TOPICS: dict[str, list[str]] = {
    "SOC_SIEM": ["soc", "siem", "security operations", "log analysis", "wazuh", "splunk"],
    "Threat_Intelligence": ["threat intelligence", "threat hunting", "ioc", "cti", "attribution"],
    "Malware_Research": ["malware", "ransomware", "reverse engineering", "botnet"],
    "LLM_Security": ["llm", "large language model", "prompt injection", "ai security", "genai"],
    "Digital_Forensics": ["forensic", "incident response", "dfir"],
    "Network_Security": ["network security", "intrusion detection", "ids", "ips", "anomaly detection"],
    "ICS_OT_Security": ["ics", "scada", "ot security", "industrial control"],
}
