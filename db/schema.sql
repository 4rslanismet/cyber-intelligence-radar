-- Cyber Intelligence Radar - basit tek-sunucu şeması
-- pgvector extension'ı embedding kolonu için gerekli (opsiyonel kullanım, ileride
-- "benzer makale / benzer olay" aramaları için).

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Pipeline durumu: her koşunun ne zaman çalıştığını tutar (zaman penceresi bunun
-- üzerinden hesaplanır -> hiçbir şey çift işlenmez, hiçbir şey atlanmaz)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_state (
    key         text PRIMARY KEY,
    value       text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Her toplama/analiz koşusunun denetim izi (coverage audit için)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collector_runs (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,           -- 'openalex' | 'crossref' | 'arxiv' | ... | 'bleepingcomputer'
    kind          text NOT NULL,           -- 'academic' | 'news'
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    query         text,
    result_count  integer,
    error         text
);

-- ---------------------------------------------------------------------------
-- Akademik makaleler
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS papers (
    id                  bigserial PRIMARY KEY,
    doi                 text UNIQUE,
    arxiv_id            text UNIQUE,
    openalex_id         text UNIQUE,
    title               text NOT NULL,
    normalized_title    text NOT NULL,
    authors             jsonb NOT NULL DEFAULT '[]',
    venue               text,
    publication_date    date,
    abstract            text,
    pdf_url             text,
    pdf_local_path       text,
    pdf_source          text,             -- 'unpaywall' | 'arxiv' | null
    analysis_type       text NOT NULL DEFAULT 'ABSTRACT_ONLY',  -- ABSTRACT_ONLY | FULL_TEXT
    source_apis         text[] NOT NULL DEFAULT '{}',
    relevance           jsonb,
    relevance_status    text NOT NULL DEFAULT 'pending', -- pending|relevant|uncertain|irrelevant
    analysis            jsonb,
    analyzed_at         timestamptz,
    notebooklm_topic    text,
    embedding           vector(1536),
    -- true ise bu makale "geçmişe yönelik tarama" (src/run_pipeline.py
    -- _maybe_collect_historical) tarafından bulundu: KEYWORDS için en çok
    -- atıf almış, güncel olmayan (bkz. HISTORICAL_CUTOFF_DAYS) makaleler.
    -- digest.py bunları "Geçmişten Öne Çıkanlar" diye ayrı gösterir.
    is_historical       boolean NOT NULL DEFAULT false,
    -- Bu makale en son ne zaman bir brifingde "Geçmişten Öne Çıkanlar"
    -- olarak gösterildi (bkz. run_pipeline._select_historical_highlights).
    -- NULL = hiç gösterilmedi. Rotasyon bunun üzerinden yapılır: her koşuda
    -- en eski gösterilen / hiç gösterilmemiş 5 tanesi seçilir, aynı 5 makale
    -- sürekli tekrar etmez.
    historical_shown_at timestamptz,
    -- OpenAlex'ten gelen atıf sayısı (yalnızca search_openalex_historical
    -- doldurur) - digest.py'daki historical_score hesabının bir girdisi.
    cited_by_count      integer,
    -- Research profiles (see cyber_radar/research/profiles.py): which
    -- profile(s) (e.g. 'default', or any custom profile ID from
    -- profiles/examples/*.yaml) caught this paper in a query/snowball -
    -- the same paper can match multiple profiles.
    matched_profiles     text[] NOT NULL DEFAULT '{}',
    -- Journal registry doğrulaması (bkz. src/research/journal_lookup.py,
    -- journal_registry tablosu). issn/eissn/publisher/document_type
    -- toplama sırasında kaynak API'den (OpenAlex/Crossref) GELDİĞİ GİBİ
    -- kaydedilir - bunlar sadece metadata. journal_verified/wos_index/
    -- journal_quartile ise SADECE journal_registry'de gerçek bir eşleşme
    -- varsa dolar - LLM'e ya da başka bir sezgisel yönteme TAHMİN
    -- ETTİRİLMEZ (bkz. proje notları: "SCIE kontrolünü bibliyografik
    -- metadata'dan tahmin etmeyelim").
    issn                 text,
    eissn                text,
    publisher            text,
    document_type        text,
    journal_verified     boolean NOT NULL DEFAULT false,
    wos_index            text,      -- ör. 'SCIE' | 'ESCI' | null (journal_registry'den)
    journal_quartile     text,      -- ör. 'Q1'..'Q4' | null (journal_registry'den)
    -- DOAJ (Directory of Open Access Journals) - journal_registry'den FARKLI:
    -- statik bir export değil, CANLI bir API (bkz. src/collectors/doaj.py) -
    -- sadece 'relevant' çıkan makaleler için (Level 4 analiz aşamasında)
    -- sorgulanır, NULL = henüz kontrol edilmedi (false ile KARIŞTIRILMAZ).
    doaj_indexed         boolean,
    -- Faz 5 "geri bildirim döngüsü": bunların hiçbiri LLM tarafından
    -- doldurulmaz, yalnızca src/telegram_listener.py (kullanıcının Telegram'da
    -- bastığı buton/yazdığı yanıt) tarafından güncellenir.
    reading_status      text NOT NULL DEFAULT 'unread', -- unread|reading|completed|skipped
    started_at          timestamptz,
    completed_at        timestamptz,
    my_note             text,      -- kullanıcının serbest metin notu
    my_takeaway         text,      -- kullanıcının kendi çıkarımı
    research_idea       text,      -- makaleden esinlenen kendi araştırma fikri
    feedback            text,      -- 'useful'|'not_useful'|'important'|'later'
    -- Sabit-kota akademik seçim (run_pipeline._select_current_papers):
    -- "5 Güncel Makale" bu koşuda yeterli yeni relevant makale yoksa son 30
    -- günlük havuzdan tamamlanır - aynı makale sürekli geri gelmesin diye
    -- historical_shown_at ile birebir aynı rotasyon deseni.
    recent_shown_at         timestamptz,
    -- "🧭 Temelden Güncele — Son 5 Yıl" seçimi (run_pipeline._select_learning_path)
    -- için aynı rotasyon deseni.
    learning_path_shown_at  timestamptz,
    -- Research Profile A/B digest bridge (config.RESEARCH_PROFILE_A_ID/
    -- _B_ID, see docs/PROFILES.md) - run_pipeline._select_profile_papers_
    -- for_digest. Same rotation pattern as recent_shown_at/
    -- learning_path_shown_at, two SEPARATE columns so a paper matching
    -- both profile slots doesn't have its rotations overwrite each other.
    research_profile_a_digest_shown_at  timestamptz,
    research_profile_b_digest_shown_at  timestamptz,
    -- Phase 2, madde 6 - bu makale için BUILDS_ON hesaplaması (bkz.
    -- src/research/citation_relationships.compute_builds_on) en son NE
    -- ZAMAN denendi. NULL = hiç denenmedi. Aynı makale için OpenCitations'a
    -- her koşuda TEKRAR sorulmasın diye (bir kez denendiyse - sonuç 0 kenar
    -- olsa bile - tekrar denenmez, bkz. run_pipeline._enrich_relationships).
    builds_on_checked_at   timestamptz,
    -- Phase 2, madde 10 (okuma durumu) - "aynı makaleyi sürekli 'Oku Şimdi'
    -- olarak önermesin" (bkz. run_pipeline._send_feedback_followups).
    -- reading_status ('unread'|'reading'|'completed'|'skipped') zaten
    -- kullanıcının fiilen etkileşimini yakalıyor - bu kolon AYRICA "hiç
    -- etkileşim olmasa bile en son NE ZAMAN önerildi" bilgisini tutuyor.
    last_recommended_at    timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers (normalized_title);
CREATE INDEX IF NOT EXISTS idx_papers_relevance_status ON papers (relevance_status);
CREATE INDEX IF NOT EXISTS idx_papers_is_historical ON papers (is_historical);
CREATE INDEX IF NOT EXISTS idx_papers_issn ON papers (issn) WHERE issn IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Journal registry: SCIE/WoS/Scopus indeks durumu için DOĞRULANMIŞ kayıt
-- (bkz. src/research/journal_lookup.py). BİLİNÇLİ OLARAK bibliyografik
-- metadata'dan (ör. atıf sayısı, yayıncı adı) TAHMİN ÜRETMİYORUZ - Clarivate
-- Web of Science Core Collection ve Scopus indeksleri dinamik değişebiliyor
-- (bir dergi SCIE'den ESCI'ye düşebilir/tersi), tek otorite kendi Master
-- Journal List/Scopus Source List export'ları. Bu tablo BOŞ başlar; veri
-- `scripts/import_journal_registry.py` ile bir CSV'den (WoS/Scopus export'u)
-- elle içeri alınır - hiçbir pipeline koşusu bu tabloya otomatik satır
-- YAZMAZ, sadece OKUR (papers.issn/eissn üzerinden eşleştirip
-- papers.journal_verified/wos_index/journal_quartile'ı doldurur).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_registry (
    issn            text,
    eissn           text,
    journal_name    text NOT NULL,
    wos_index       text,       -- 'SCIE' | 'SSCI' | 'AHCI' | 'ESCI' | null
    scie            boolean,
    jcr_quartile    text,       -- 'Q1'..'Q4' | null
    jcr_year        integer,
    scopus_indexed  boolean,
    scopus_quartile text,
    source          text,       -- ör. 'wos_master_journal_list_2026' | 'scopus_source_list_2026' | 'manual'
    verified_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_journal_registry_issn ON journal_registry (issn);
CREATE INDEX IF NOT EXISTS idx_journal_registry_eissn ON journal_registry (eissn);

-- ---------------------------------------------------------------------------
-- Haber / olay kayıtları (aynı olayın farklı kaynaklardaki haberleri tek satırda birleşir)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_events (
    id                bigserial PRIMARY KEY,
    title             text NOT NULL,
    dedup_key         text,                 -- normalize edilmiş başlık + öne çıkan CVE
    summary           text,
    sources           jsonb NOT NULL DEFAULT '[]',  -- [{"name":"BleepingComputer","url":"..."}]
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_updated_at   timestamptz NOT NULL DEFAULT now(),
    published_at      timestamptz,
    raw_text          text,
    cves              text[] NOT NULL DEFAULT '{}',
    vendors           text[] NOT NULL DEFAULT '{}',
    products          text[] NOT NULL DEFAULT '{}',
    relevance         jsonb,
    relevance_status  text NOT NULL DEFAULT 'pending',
    analysis          jsonb,
    analyzed_at       timestamptz,
    cisa_kev          boolean NOT NULL DEFAULT false,
    priority_score    integer,
    priority_label    text,
    -- Faz 5 "geri bildirim döngüsü" (bkz. papers tablosundaki aynı isimli
    -- kolonların yorumu) - src/telegram_listener.py tarafından güncellenir.
    reading_status    text NOT NULL DEFAULT 'unread',
    completed_at      timestamptz,
    my_note           text,
    feedback          text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    -- 2026-09-10 kök neden analizi düzeltmesi (bkz. run_pipeline.
    -- _select_news_for_digest): papers.recent_shown_at ile AYNI rotasyon
    -- deseni - bu haber en son ne zaman brifingde GÖSTERİLDİ (analiz
    -- edildiği an DEĞİL). NULL = hiç gösterilmedi, backfill'de önceliklidir.
    digest_shown_at   timestamptz,
    -- 2026-09-14 kök neden düzeltmesi ("sabah-akşam aynı haber tekrar
    -- gösteriliyor"): SADECE dedup.is_material_news_update() TRUE dönerse
    -- ileri alınır - last_updated_at'in aksine "başka bir kaynak aynı
    -- haberi tekrar yazdı" gibi içeriksiz güncellemelerde İLERLEMEZ.
    -- _select_news_for_digest bunu, aynı gün içinde zaten gösterilmiş bir
    -- haberi (material_update_at > digest_shown_at DEĞİLSE) tekrar aday
    -- havuzuna almamak için kullanır.
    material_update_at timestamptz,
    -- 2026-09-15 (madde 5/6 - "conditional re-analysis"): NULL değilse, bu
    -- satır DAHA ÖNCE analiz edilmiş ama _find_or_merge_news_event'te
    -- gerçek yeni deterministik kanıt (yeni CVE/regex-IOC) bulunduğu için
    -- analyzed_at NULL'a çekilip koşullu re-analiz adayı yapılmış demektir
    -- (bkz. _analyze_relevant_news - mevcut LLM bütçesinden geçer, ayrı bir
    -- sınırsız çağrı yolu YOK). Değer "new_cve"/"new_ioc_evidence" ya da
    -- "new_cve+new_ioc_evidence" olabilir - insan-okunur, gözlemlenebilir
    -- bir sebep. Re-analiz tamamlanınca NULL'a döner.
    pending_reanalysis_reason text
);
CREATE INDEX IF NOT EXISTS idx_news_dedup_key ON news_events (dedup_key);
CREATE INDEX IF NOT EXISTS idx_news_relevance_status ON news_events (relevance_status);
CREATE INDEX IF NOT EXISTS idx_news_cves ON news_events USING gin (cves);
CREATE INDEX IF NOT EXISTS idx_news_digest_shown_at ON news_events (digest_shown_at);

-- ---------------------------------------------------------------------------
-- Düşük güvenli / belirsiz sınıflandırmalar buraya düşer, otomatik silinmez
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_queue (
    id          bigserial PRIMARY KEY,
    item_type   text NOT NULL,   -- 'paper' | 'news'
    item_id     bigint NOT NULL,
    reason      text,
    confidence  real,
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved    boolean NOT NULL DEFAULT false
);

-- ---------------------------------------------------------------------------
-- Paket 4B - Systematic Screening (bkz. src/research/screening.py). Discovery
-- relevance'tan (papers.relevance_status, src/llm/relevance.py) TAMAMEN
-- AYRI bir kavram - "bu kayıt BELİRLİ bir research profile'ın literatür
-- korpusuna dahil edilmeli mi?" metodolojik kararı. papers tablosunu
-- OVERWRITE ETMEZ.
--
-- Geçmiş karar SİLİNMEZ/UPDATE EDİLMEZ - yeni bir karar supersedes_decision_id
-- ile eskisini "supersede" eder, akademik audit trail (PRISMA) korunur.
-- Final durum LLM DEĞİL, deterministik bir resolver (screening.
-- resolve_final_decision) tarafından hesaplanır: human > full_text[geçerli]
-- > title_abstract > metadata önceliğiyle.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- NotebookLM'e hangi makalenin hangi periyot/konu dosyasına yazıldığının kaydı
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- CISA KEV saatlik izleyicinin (src/kev_watch.py) "bu CVE için zaten uyarı
-- gönderdim" kaydı - günlük pipeline'ın 12+ saat bekletmeden, kritik/aktif
-- exploit edilen CVE'leri anında Telegram'a düşürmesi için.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Faz 5 "geri bildirim döngüsü": her interaktif (butonlu) Telegram mesajının
-- hangi makale/habere ait olduğunun kaydı. src/telegram_listener.py bir
-- callback_query veya bu mesaja verilen bir yanıt (reply) aldığında,
-- reply_to_message.message_id ile burayı sorgulayıp hangi papers/news_events
-- satırını güncelleyeceğini bulur.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_message_map (
    message_id  bigint PRIMARY KEY,
    item_type   text NOT NULL,   -- 'paper' | 'news'
    item_id     bigint NOT NULL,
    -- 📝 Not Ekle / 💡 Fikir Ekle butonlarıyla gönderilen "yaz" isteği
    -- mesajları için: bu mesaja verilen yanıt hangi kolona yazılacak
    -- ('my_note' | 'research_idea'). NULL ise normal bir brifing/öğe
    -- mesajı - butonlar bu mesaja değil, ayrı gönderilen mesaja eklenir.
    field       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Research Collections (bkz. src/research/collections.py): kullanıcının
-- NİYET bazlı kümeleri - '📄 SCI'ya Ekle'/'🎓 Teze Ekle'/'👀 Merak Listesi'.
-- BİLİNÇLİ OLARAK feedback/reading_status/relevance_status/journal_verified/
-- screening_decisions İLE KARIŞTIRILMAZ - hiçbirini overwrite etmez, hiçbiri
-- bunu etkilemez. Bir makale birden fazla koleksiyonda olabilir (PK
-- (paper_id, collection) bunu doğal olarak sağlar).
-- ---------------------------------------------------------------------------

-- '🔎 Benzerlerini Tara': kullanıcının Telegram'dan tetiklediği, manuel
-- citation snowballing istekleri. src/collectors/citation_graph.py'nin
-- otomatik (confidence-sıralı) snowball akışından AYRI - burada seed AÇIKÇA
-- kullanıcı tarafından seçilir. processed_at NULL = henüz işlenmedi.

-- ---------------------------------------------------------------------------
-- Faz 6 "kişisel sıralama": LLM'e HESAPLATILMIYOR - Telegram buton
-- davranışından (bkz. telegram_listener.py + src/ranking.py) deterministik
-- Python koduyla hesaplanır. Bilinçli mimari karar: model değişse/güncellense
-- bile kullanıcının tercih profili sabit kalsın.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS personal_preference_scores (
    dimension   text NOT NULL,   -- 'domain' | 'paper_role' | 'news_event_type'
    key         text NOT NULL,
    score       numeric NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dimension, key)
);

-- Her buton basışının denetim izi - personal_preference_scores'un nasıl bu
-- hale geldiğini geriye dönük açıklar, hata ayıklamayı ve "bu skoru neden
-- aldım" sorusunu cevaplamayı mümkün kılar.
CREATE TABLE IF NOT EXISTS personal_feedback_log (
    id          bigserial PRIMARY KEY,
    item_type   text NOT NULL,
    item_id     bigint NOT NULL,
    action      text NOT NULL,   -- 'useful'|'not_useful'|'important'|'later'|'done'|'never_show'
    points      numeric NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Faz 6 "spaced repetition": bir makale COMPLETED olduğunda (yalnızca
-- MUST_READ veya FOUNDATION rolündekiler için, bkz. src/ranking.py) +1/+3/+7/
-- +21 gün için birer satır açılır. src/spaced_repetition.py (saatlik timer)
-- vadesi gelenleri bulup post_reading_questions'ı Telegram'a gönderir.
-- ---------------------------------------------------------------------------

-- Phase 2, madde 6 (2026-09-10) - bkz. src/research/citation_relationships.py.
-- BUILDS_ON/FOUNDATION_FOR paper<->paper kenarları SADECE gerçek
-- reference/citation metadata'sıyla (OpenCitations) kurulur, LLM tarafından
-- ASLA doğrudan üretilmez - append-only, deterministik, dış kaynaktan
-- doğrulanmış bir tablo (screening_decisions ile AYNI "audit trail" ilkesi).
CREATE TABLE IF NOT EXISTS paper_relationships (
    id                  bigserial PRIMARY KEY,
    paper_id            bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    related_paper_id    bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    relationship_type   text NOT NULL, -- 'builds_on' | 'foundation_for' (simetrik çift olarak eklenir)
    verified_via        text NOT NULL, -- ör. 'opencitations_reference_doi' - HANGİ dış kaynakla doğrulandığı
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (paper_id, related_paper_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_paper_relationships_paper ON paper_relationships (paper_id, relationship_type);

-- ---------------------------------------------------------------------------
-- 2026-09-13 V1 Finalizasyon + 13 Ağu-13 Eyl recovery (bkz. src/recovery/,
-- scripts/run_recovery.py). Additive-only - hiçbir mevcut kolon/tablo
-- değiştirilmedi/silinmedi.
--
-- recovery_runs/recovery_checkpoints: resume-safe, chunked bir geçmiş
-- tarama koşusunun durumu. Bir recovery_run birden fazla (profile_id,
-- source, window_start, window_end) checkpoint'inden oluşur; server/reboot/
-- API hatasında sadece status != 'done' olan checkpoint'ler yeniden
-- denenir, tüm ay baştan başlamaz (bkz. run_recovery.py --resume).
-- ---------------------------------------------------------------------------


-- collector_runs.run_type: normal incremental koşuları recovery_backfill
-- koşularından ayırır (bkz. run_pipeline._coverage_warning/
-- _source_anomaly_warnings - artık WHERE run_type='incremental' filtreli,
-- recovery koşuları normal coverage baseline'ını BOZMAZ).
ALTER TABLE collector_runs ADD COLUMN IF NOT EXISTS run_type text NOT NULL DEFAULT 'incremental';
ALTER TABLE collector_runs ADD COLUMN IF NOT EXISTS recovery_run_id bigint;  -- no recovery module shipped publicly; column kept for schema/code parity, always NULL

-- papers.discovery_source/discovery_seed_paper_id: bir makale normal günlük
-- taramayla mı (NULL), recovery backfill'iyle mi ('recovery_backfill'),
-- yoksa citation snowball ile mi ('citation_snowball', bkz.
-- discovery_seed_paper_id) bulundu - recovery penceresi DIŞINDAKİ (daha
-- eski) snowball sonuçlarının "missed_publications" sayısına yanlışlıkla
-- karışmaması için (bkz. run_recovery.py, spec madde L/M).
ALTER TABLE papers ADD COLUMN IF NOT EXISTS discovery_source text;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS discovery_seed_paper_id bigint REFERENCES papers(id);
