"""dedup.is_material_news_update - deterministik "old vs new" karşılaştırıcı
(bkz. 2026-09-14 kök neden raporu, madde: "material update modelini
düzelt"). TAMAMEN saf fonksiyon testleri - DB/ağ/LLM YOK."""
from __future__ import annotations

from cyber_radar.dedup import is_material_news_update


def _event(cves=None, cisa_kev=False, priority_label=None, analysis=None):
    return {"cves": cves or [], "cisa_kev": cisa_kev, "priority_label": priority_label, "analysis": analysis or {}}


# ---------------------------------------------------------------------------
# Madde 2: material SAYILMAMASI gerekenler
# ---------------------------------------------------------------------------
def test_same_event_source_repeat_not_material():
    """Aynı bilgiyle tekrar 'görülmesi' (title/url/sources bu fonksiyona hiç
    girmiyor) - hiçbir yapılandırılmış alan değişmedi."""
    old = _event(cves=["CVE-2026-1111"], cisa_kev=False, priority_label="LOW", analysis={"my_relevance": "LOW"})
    new = _event(cves=["CVE-2026-1111"], cisa_kev=False, priority_label="LOW", analysis={"my_relevance": "LOW"})
    assert is_material_news_update(old, new) is False


def test_title_only_change_not_material():
    """Bu fonksiyon title'a hiç bakmıyor - çağıran taraf title'ı zaten
    old/new_event sözlüğüne dahil etmiyor, ama yine de netlik için: aynı
    yapılandırılmış veriyle, sadece 'başlık değişti' senaryosunda False."""
    old = _event(cves=["CVE-2026-1111"], priority_label="MEDIUM")
    new = _event(cves=["CVE-2026-1111"], priority_label="MEDIUM")
    assert is_material_news_update(old, new) is False


def test_last_seen_change_not_material():
    """last_updated_at/last_seen_at bu fonksiyona hiç parametre olarak
    geçilmiyor - fonksiyon imzası zaten bunları TANIMIYOR, dolayısıyla
    aynı yapılandırılmış veriyle 'zaman ilerledi' hiçbir fark yaratmaz."""
    old = _event(cves=["CVE-2026-1111"])
    new = _event(cves=["CVE-2026-1111"])
    assert is_material_news_update(old, new) is False


def test_same_cve_different_order_not_material():
    old = _event(cves=["CVE-2026-2222", "CVE-2026-1111"])
    new = _event(cves=["CVE-2026-1111", "CVE-2026-2222"])
    assert is_material_news_update(old, new) is False


def test_duplicate_ioc_not_material():
    """Aynı IOC farklı case/whitespace/sırayla tekrar gelirse material
    SAYILMAZ - normalize edilmiş karşılaştırma."""
    old = _event(analysis={"ioc": {"ips": ["1.2.3.4"], "domains": ["Evil.com"]}})
    new = _event(analysis={"ioc": {"ips": [" 1.2.3.4 "], "domains": ["evil.com"]}})
    assert is_material_news_update(old, new) is False


def test_mitigation_wording_paraphrase_not_material():
    old = _event(analysis={"mitigation": ["Upgrade to version X"]})
    new = _event(analysis={"mitigation": ["upgrade   to version x"]})  # normalize sonrası AYNI
    assert is_material_news_update(old, new) is False


def test_severity_decrease_not_material_by_default():
    """Kullanıcı isteği: severity düşüşü varsayılan olarak material
    SAYILMAZ (sadece anlamlı YÜKSELİŞ tetikler)."""
    old = _event(priority_label="HIGH")
    new = _event(priority_label="LOW")
    assert is_material_news_update(old, new) is False


def test_active_exploitation_true_to_false_not_material():
    """Kullanıcı isteği: 'true -> false gibi anlamsız ters güncelleme'
    otomatik material kabul edilmemeli."""
    old = _event(analysis={"active_exploitation": True})
    new = _event(analysis={"active_exploitation": False})
    assert is_material_news_update(old, new) is False


# ---------------------------------------------------------------------------
# Madde 1: material SAYILMASI gerekenler
# ---------------------------------------------------------------------------
def test_new_cve_is_material():
    old = _event(cves=["CVE-2026-1111"])
    new = _event(cves=["CVE-2026-1111", "CVE-2026-2222"])
    assert is_material_news_update(old, new) is True


def test_kev_false_to_true_is_material():
    old = _event(cisa_kev=False)
    new = _event(cisa_kev=True)
    assert is_material_news_update(old, new) is True


def test_active_exploitation_false_to_true_is_material():
    old = _event(analysis={"active_exploitation": False})
    new = _event(analysis={"active_exploitation": True})
    assert is_material_news_update(old, new) is True


def test_exploit_status_upgrade_poc_to_active_is_material():
    old = _event(analysis={"exploit_status": "poc"})
    new = _event(analysis={"exploit_status": "active_exploitation"})
    assert is_material_news_update(old, new) is True


def test_new_ioc_is_material():
    old = _event(analysis={"ioc": {"ips": ["1.2.3.4"]}})
    new = _event(analysis={"ioc": {"ips": ["1.2.3.4", "5.6.7.8"]}})
    assert is_material_news_update(old, new) is True


def test_new_hunt_artifact_is_material():
    old = _event(analysis={"process_names": ["powershell.exe"]})
    new = _event(analysis={"process_names": ["powershell.exe", "rundll32.exe"]})
    assert is_material_news_update(old, new) is True


def test_new_hunt_query_is_material():
    old = _event(analysis={"hunt_query": None})
    new = _event(analysis={"hunt_query": "w3wp.exe -> cmd.exe"})
    assert is_material_news_update(old, new) is True


def test_affected_versions_meaningfully_changed_is_material():
    old = _event(analysis={"affected_versions": ["Chrome < 152"]})
    new = _event(analysis={"affected_versions": ["Chrome 150-152.0.7977.81"]})
    assert is_material_news_update(old, new) is True


def test_fixed_version_added_is_material():
    old = _event(analysis={"fixed_versions": []})
    new = _event(analysis={"fixed_versions": ["152.0.7977.82+"]})
    assert is_material_news_update(old, new) is True


def test_mitigation_added_is_material():
    old = _event(analysis={"mitigation": []})
    new = _event(analysis={"mitigation": ["Apply vendor hotfix Z"]})
    assert is_material_news_update(old, new) is True


def test_severity_increase_is_material():
    old = _event(priority_label="LOW")
    new = _event(priority_label="HIGH")
    assert is_material_news_update(old, new) is True


def test_relevance_increase_is_material():
    old = _event(analysis={"my_relevance": "MEDIUM"})
    new = _event(analysis={"my_relevance": "HIGH"})
    assert is_material_news_update(old, new) is True


# ---------------------------------------------------------------------------
# 2026-09-15 (madde 2 tamamlandı - şemaya eklenen yeni alanlar): email/file
# path/registry artifact/service/scheduled task/mutex/user-agent.
# ---------------------------------------------------------------------------
def test_new_email_ioc_is_material():
    old = _event(analysis={"ioc": {"emails": ["a@example.com"]}})
    new = _event(analysis={"ioc": {"emails": ["a@example.com", "b@example.com"]}})
    assert is_material_news_update(old, new) is True


def test_same_email_different_case_not_material():
    old = _event(analysis={"ioc": {"emails": ["Attacker@Example.com"]}})
    new = _event(analysis={"ioc": {"emails": ["attacker@example.com"]}})
    assert is_material_news_update(old, new) is False


def test_new_file_path_is_material():
    old = _event(analysis={"file_paths": [r"C:\Users\Public\a.exe"]})
    new = _event(analysis={"file_paths": [r"C:\Users\Public\a.exe", r"C:\Users\Public\b.exe"]})
    assert is_material_news_update(old, new) is True


def test_duplicate_file_path_not_material():
    """Sadece fazladan boşluk farkı - case KORUNUR (madde 3: file path için
    case-insensitivity istenmedi, sadece whitespace normalize edilir)."""
    old = _event(analysis={"file_paths": [r"C:\Users\Public\a.exe"]})
    new = _event(analysis={"file_paths": [r"C:\Users\Public\a.exe  "]})
    assert is_material_news_update(old, new) is False


def test_new_registry_artifact_is_material():
    old = _event(analysis={"registry_artifacts": []})
    new = _event(analysis={"registry_artifacts": ["RunOnce=evil.exe"]})
    assert is_material_news_update(old, new) is True


def test_duplicate_registry_path_different_slash_case_not_material():
    old = _event(analysis={"registry_paths": [r"HKCU\Software\Evil"]})
    new = _event(analysis={"registry_paths": ["hkcu/software/evil"]})
    assert is_material_news_update(old, new) is False


def test_new_service_is_material():
    old = _event(analysis={"services": []})
    new = _event(analysis={"services": ["WindowsUpdateHelper"]})
    assert is_material_news_update(old, new) is True


def test_new_scheduled_task_is_material():
    old = _event(analysis={"scheduled_tasks": []})
    new = _event(analysis={"scheduled_tasks": ["MicrosoftEdgeUpdateTaskMachine"]})
    assert is_material_news_update(old, new) is True


def test_new_mutex_is_material():
    old = _event(analysis={"mutexes": []})
    new = _event(analysis={"mutexes": ["Global\\\\evil_mutex_v2"]})
    assert is_material_news_update(old, new) is True


def test_new_user_agent_is_material():
    old = _event(analysis={"user_agents": []})
    new = _event(analysis={"user_agents": ["Mozilla/5.0 (evil-bot/1.0)"]})
    assert is_material_news_update(old, new) is True


def test_ip_canonical_form_not_material():
    """Madde 3: 'IP canonical form mümkünse' - öndeki sıfır farkı material
    SAYILMAMALI."""
    old = _event(analysis={"ioc": {"ips": ["192.168.001.001"]}})
    new = _event(analysis={"ioc": {"ips": ["192.168.1.1"]}})
    assert is_material_news_update(old, new) is False
