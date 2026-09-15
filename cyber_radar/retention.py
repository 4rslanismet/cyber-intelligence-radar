"""Disk temizliği: Google Drive'a başarıyla yüklenmiş dosyaları, üretildikten
config.LOCAL_RETENTION_DAYS (varsayılan 2) gün sonra sunucudan siler.

Katı kural: bir dosya ASLA önce silinip sonra "yüklenmiş olsun" varsayılmaz -
her zaman önce upload_or_update() başarıyla döner, sonra silme yapılır. Drive
kapalıysa (GDRIVE_ENABLED=false) ya da token yoksa hiçbir şey silinmez -
disk dolabilir ama veri kaybı olmaz.

Kapsam (kullanıcı tercihi: hepsi):
  - data/reports/*.md               (günlük VE haftalık/aylık brifingler - digest.py
                                      ve weekly_digest.py ikisi de aynı klasöre yazar)
  - data/notebooklm/<Konu>/*.md     (periyot dosyaları - sadece KAPANMIŞ periyotlar)
  - data/notebooklm/<Konu>/*_pdfs/  (yüksek değerli makale PDF'leri - aynı periyotla birlikte)
  - data/academic/pdf/*             (ham PDF önbelleği - analiz sonrası artık gereksiz)
  - data/notebooklm/_index/collected_papers.json (manifest - HER ZAMAN senkron edilir, ASLA silinmez)
  - data/db_backups/*.dump          (PostgreSQL yedeği - HER koşuda yeni bir dump alınır,
                                      Drive'a yüklenir; eskiler yerelden silinir, Drive'da kalıcı durur)
"""
from __future__ import annotations

import os
import shutil
from datetime import date, datetime, timedelta

from . import config, db_backup, drive_queue, gdrive
from .notebooklm_export import period_end_date


def _mtime_date(path: str) -> date:
    return datetime.fromtimestamp(os.path.getmtime(path)).date()


def _ensure_root_folder() -> str:
    if config.GDRIVE_ROOT_FOLDER_ID:
        return config.GDRIVE_ROOT_FOLDER_ID
    return gdrive.ensure_folder(config.GDRIVE_ROOT_FOLDER_NAME)


def _sync_manifest(root_id: str) -> None:
    if not os.path.exists(config.NOTEBOOKLM_MANIFEST_FILE):
        return
    index_folder = gdrive.ensure_folder("_index", root_id)
    gdrive.upload_or_update(config.NOTEBOOKLM_MANIFEST_FILE, index_folder)


def _sync_and_purge_notebooklm(root_id: str, cutoff: date, logs: list[str]) -> None:
    if not os.path.isdir(config.NOTEBOOKLM_DIR):
        return
    nb_root = gdrive.ensure_folder("notebooklm", root_id)

    for topic in sorted(os.listdir(config.NOTEBOOKLM_DIR)):
        topic_path = os.path.join(config.NOTEBOOKLM_DIR, topic)
        if topic == "_index" or not os.path.isdir(topic_path):
            continue
        topic_folder = gdrive.ensure_folder(topic, nb_root)

        for entry in sorted(os.listdir(topic_path)):
            entry_path = os.path.join(topic_path, entry)

            if entry.endswith(".md"):
                period = entry[: -len(".md")]
                end = period_end_date(period)
                if end is None or end >= cutoff:
                    continue  # periyot henüz kapanmadı, dokunma
                gdrive.upload_or_update(entry_path, topic_folder)
                os.remove(entry_path)
                logs.append(f"📤 notebooklm/{topic}/{entry} → Drive'a yüklendi, sunucudan silindi.")

            elif entry.endswith("_pdfs") and os.path.isdir(entry_path):
                period = entry[: -len("_pdfs")]
                end = period_end_date(period)
                if end is None or end >= cutoff:
                    continue
                pdf_files = [p for p in os.listdir(entry_path) if os.path.isfile(os.path.join(entry_path, p))]
                if pdf_files:
                    pdf_folder = gdrive.ensure_folder(entry, topic_folder)
                    for pdf_name in pdf_files:
                        gdrive.upload_or_update(os.path.join(entry_path, pdf_name), pdf_folder)
                shutil.rmtree(entry_path)
                logs.append(
                    f"📤 notebooklm/{topic}/{entry}/ → Drive'a yüklendi ({len(pdf_files)} PDF), sunucudan silindi."
                )


def _sync_and_purge_reports(root_id: str, cutoff: date, logs: list[str]) -> None:
    if not os.path.isdir(config.REPORTS_DIR):
        return
    reports_folder = gdrive.ensure_folder("reports", root_id)
    for entry in sorted(os.listdir(config.REPORTS_DIR)):
        entry_path = os.path.join(config.REPORTS_DIR, entry)
        if not os.path.isfile(entry_path):
            continue
        # Her koşuda yükle (küçük dosya, ucuz) - sadece eski olanı sil.
        gdrive.upload_or_update(entry_path, reports_folder)
        if _mtime_date(entry_path) < cutoff:
            os.remove(entry_path)
            logs.append(f"📤 reports/{entry} → Drive'a yüklendi, sunucudan silindi.")


def _sync_and_purge_pdf_cache(root_id: str, logs: list[str]) -> None:
    """LOCAL_RETENTION_DAYS'ten AYRI, kendi PDF_CACHE_RETENTION_DAYS'ini
    kullanır (bkz. config.py) - ham PDF'ler analiz aynı koşuda bittiği için
    diğer kategoriler kadar (varsayılan 2 gün) beklemesine gerek yok."""
    if not os.path.isdir(config.PDF_DIR):
        return
    pdf_cache_folder = gdrive.ensure_folder("academic_pdf_cache", root_id)
    cutoff = date.today() - timedelta(days=config.PDF_CACHE_RETENTION_DAYS)
    for entry in sorted(os.listdir(config.PDF_DIR)):
        entry_path = os.path.join(config.PDF_DIR, entry)
        if not os.path.isfile(entry_path):
            continue
        # PDF_CACHE_RETENTION_DAYS=0 (varsayılan): yaşına bakmadan HER koşuda
        # temizle - bugün indirilmiş bir PDF'in mtime'ı == cutoff olacağından
        # normal ">=" mtime kontrolü (diğer kategorilerin kullandığı) onu bir
        # sonraki koşuya kadar atlar; 0 günde bunu İSTEMİYORUZ.
        if config.PDF_CACHE_RETENTION_DAYS > 0 and _mtime_date(entry_path) >= cutoff:
            continue
        gdrive.upload_or_update(entry_path, pdf_cache_folder)
        os.remove(entry_path)
        logs.append(f"📤 academic/pdf/{entry} → Drive'a yüklendi, sunucudan silindi.")


def _backup_and_purge_database(root_id: str, cutoff: date, logs: list[str]) -> None:
    """Her koşuda YENİ bir pg_dump alır (küçük DB, saniyeler sürer), hemen
    Drive'a yükler. Eski yerel dump'lar (>= retention gün) silinir - Drive'da
    hepsi kalıcı durur (felaket kurtarma için: python3 -m src.db_restore)."""
    try:
        dump_path = db_backup.create_backup()
    except Exception as e:  # noqa: BLE001 - yedek alınamazsa senkronun geri
        # kalanı (raporlar/notebooklm/pdf) yine de devam etsin.
        logs.append(f"⚠️ DB yedeği alınamadı: {e}")
        return

    backup_folder = gdrive.ensure_folder("db_backups", root_id)
    gdrive.upload_or_update(dump_path, backup_folder)
    logs.append(f"📤 db_backups/{os.path.basename(dump_path)} → Drive'a yüklendi.")

    for entry in sorted(os.listdir(db_backup.DB_BACKUP_DIR)):
        entry_path = os.path.join(db_backup.DB_BACKUP_DIR, entry)
        if os.path.isfile(entry_path) and _mtime_date(entry_path) < cutoff:
            os.remove(entry_path)
            logs.append(f"🗑️ db_backups/{entry} sunucudan silindi (Drive'da kalıcı duruyor).")


def _enqueue_notebooklm(state: dict, cutoff: date) -> None:
    """Direct moddaki AYNI 'sadece kapanmış periyot' kapısı - açık periyot
    dosyaları henüz kuyruğa bile eklenmez (bkz. _sync_and_purge_notebooklm)."""
    if not os.path.isdir(config.NOTEBOOKLM_DIR):
        return
    for topic in sorted(os.listdir(config.NOTEBOOKLM_DIR)):
        topic_path = os.path.join(config.NOTEBOOKLM_DIR, topic)
        if topic == "_index" or not os.path.isdir(topic_path):
            continue
        for entry in sorted(os.listdir(topic_path)):
            entry_path = os.path.join(topic_path, entry)
            if entry.endswith(".md"):
                end = period_end_date(entry[: -len(".md")])
                if end is None or end >= cutoff:
                    continue
                drive_queue.enqueue(state, entry_path)
            elif entry.endswith("_pdfs") and os.path.isdir(entry_path):
                end = period_end_date(entry[: -len("_pdfs")])
                if end is None or end >= cutoff:
                    continue
                for pdf_name in os.listdir(entry_path):
                    pdf_path = os.path.join(entry_path, pdf_name)
                    if os.path.isfile(pdf_path):
                        drive_queue.enqueue(state, pdf_path)


def _queued_sync_and_cleanup() -> list[str]:
    """GDRIVE_SYNC_MODE='queued': ağ çağrısı YOK, sadece (1) taze bir DB
    yedeği alır (bu mod bağımsız bir ihtiyaç), (2) üretilmiş dosyaları
    kalıcı kuyruğa ekler, (3) kuyruğun ZATEN doğruladığı + retention süresi
    geçmiş dosyaları yerelden siler. Gerçek Drive yüklemesi ayrı
    (cyber-radar-drive-sync.timer -> src/drive_worker.run_worker())."""
    logs: list[str] = []
    try:
        dump_path = db_backup.create_backup()
        logs.append(f"📋 DB yedeği alındı, kuyruğa eklenecek: {os.path.basename(dump_path)}")
    except Exception as e:  # noqa: BLE001 - yedek alınamazsa kuyruğa ekleme yine de devam etsin
        logs.append(f"⚠️ DB yedeği alınamadı: {e}")

    state = drive_queue.load_state()
    added = drive_queue.scan_allowed_roots(state)  # reports/db_backups/research/academic_pdf (allowed-roots)
    cutoff = date.today() - timedelta(days=config.LOCAL_RETENTION_DAYS)
    _enqueue_notebooklm(state, cutoff)  # notebooklm/_pdfs allowed-roots DIŞINDaysa da açıkça eklenir
    if os.path.exists(config.NOTEBOOKLM_MANIFEST_FILE):
        drive_queue.enqueue(state, config.NOTEBOOKLM_MANIFEST_FILE)
    drive_queue.save_state(state)
    logs.append(f"📥 {added} yeni dosya Drive kuyruğuna eklendi (yükleme ayrı worker'da).")

    purge_logs = drive_queue.purge_retained_files(
        state,
        retention_days_by_folder={"db_backups": config.LOCAL_RETENTION_DAYS, "papers": config.PDF_CACHE_RETENTION_DAYS},
        default_days=config.LOCAL_RETENTION_DAYS,
        never_delete_paths={config.NOTEBOOKLM_MANIFEST_FILE},
    )
    drive_queue.save_state(state)
    logs.extend(purge_logs)
    return logs


def sync_and_cleanup() -> list[str]:
    """run_pipeline.main() sonunda çağrılır. Döner: insan-okunur işlem
    logları (brifinge eklenebilir). GDRIVE_SYNC_MODE='queued' iken gerçek
    Drive ağ çağrısı YAPMAZ - bkz. _queued_sync_and_cleanup()."""
    if not config.GDRIVE_ENABLED:
        return []

    if config.GDRIVE_SYNC_MODE == "queued":
        return _queued_sync_and_cleanup()

    if not gdrive.is_configured():
        return [
            "⚠️ GDRIVE_ENABLED=true ama Google Drive token'ı yok - "
            "`python3 -m src.gdrive_auth` çalıştırın. Bu koşuda hiçbir dosya silinmedi."
        ]

    logs: list[str] = []
    try:
        root_id = _ensure_root_folder()
        _sync_manifest(root_id)
        cutoff = date.today() - timedelta(days=config.LOCAL_RETENTION_DAYS)
        _backup_and_purge_database(root_id, cutoff, logs)
        _sync_and_purge_notebooklm(root_id, cutoff, logs)
        _sync_and_purge_reports(root_id, cutoff, logs)
        _sync_and_purge_pdf_cache(root_id, logs)
    except Exception as e:  # noqa: BLE001 - Drive senkronu pipeline'ı düşürmesin
        logs.append(f"⚠️ Drive senkronu sırasında hata, bu koşuda temizlik atlandı: {e}")
    return logs
