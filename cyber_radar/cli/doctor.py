"""`cyber-radar doctor` - diagnostic health check.

Reuses existing health-check building blocks where they exist (source
anomaly detection lives in run_pipeline.py and is exercised live during a
real run; this command focuses on the checks a user needs BEFORE their
first run: environment, connectivity, permissions). Never prints a
secret value - only whether one is set/reachable.

Exit code: 0 if no FAIL, 1 if any FAIL.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


def _check_python_version() -> CheckResult:
    v = sys.version_info
    if v >= (3, 11):
        return CheckResult("Python version", PASS, f"{v.major}.{v.minor}.{v.micro}")
    return CheckResult("Python version", FAIL, f"{v.major}.{v.minor}.{v.micro} - need >=3.11")


def _check_packages() -> CheckResult:
    required = ["httpx", "feedparser", "psycopg", "dotenv", "google.genai", "tenacity", "pymupdf", "yaml", "jsonschema"]
    missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]
    if not missing:
        return CheckResult("Required packages", PASS, f"{len(required)} packages found")
    return CheckResult("Required packages", FAIL, f"missing: {', '.join(missing)} - run: pip install -r requirements.txt")


def _check_database() -> CheckResult:
    try:
        from .. import config, db
    except Exception as e:  # noqa: BLE001
        return CheckResult("Database connectivity", FAIL, f"config/db import failed: {e}")
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        return CheckResult("Database connectivity", PASS, "connected")
    except Exception as e:  # noqa: BLE001
        return CheckResult("Database connectivity", FAIL, f"cannot connect - {type(e).__name__}: {e}")


def _check_schema() -> CheckResult:
    try:
        from .. import config, db
    except Exception as e:  # noqa: BLE001
        return CheckResult("Database schema", FAIL, f"config/db import failed: {e}")
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='public' AND table_name='papers'"
            ).fetchone()
        if row and row["n"]:
            return CheckResult("Database schema", PASS, "papers table found")
        return CheckResult("Database schema", WARN, "schema not initialized - run: cyber-radar db init")
    except Exception as e:  # noqa: BLE001
        return CheckResult("Database schema", WARN, f"could not check (is the DB reachable?) - {e}")


def _check_directories() -> CheckResult:
    try:
        from .. import config
    except Exception as e:  # noqa: BLE001
        return CheckResult("Data directories", FAIL, f"config import failed: {e}")
    problems = []
    for d in (config.DATA_DIR, config.REPORTS_DIR):
        try:
            os.makedirs(d, exist_ok=True)
            test_file = os.path.join(d, ".doctor_write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except OSError as e:
            problems.append(f"{d}: {e}")
    if not problems:
        return CheckResult("Data directories", PASS, f"{config.DATA_DIR} writable")
    return CheckResult("Data directories", FAIL, "; ".join(problems))


def _check_disk_space() -> CheckResult:
    try:
        from .. import config
    except Exception as e:  # noqa: BLE001
        return CheckResult("Disk space", WARN, f"config import failed: {e}")
    try:
        usage = shutil.disk_usage(config.BASE_DIR)
        free_gb = usage.free / (1024**3)
    except OSError as e:
        return CheckResult("Disk space", WARN, f"could not check: {e}")
    if free_gb < 1:
        return CheckResult("Disk space", FAIL, f"{free_gb:.1f} GB free - very low")
    if free_gb < 5:
        return CheckResult("Disk space", WARN, f"{free_gb:.1f} GB free")
    return CheckResult("Disk space", PASS, f"{free_gb:.1f} GB free")


def _check_llm_config() -> CheckResult:
    try:
        from .. import config
    except Exception as e:  # noqa: BLE001
        return CheckResult("LLM configuration", FAIL, f"config import failed: {e}")
    if not config.GEMINI_API_KEY:
        return CheckResult("LLM configuration", FAIL, "GEMINI_API_KEY not set")
    if config.GEMINI_DAILY_REQUEST_LIMIT > 100:
        return CheckResult(
            "LLM configuration", WARN,
            f"GEMINI_DAILY_REQUEST_LIMIT={config.GEMINI_DAILY_REQUEST_LIMIT} looks high - "
            "confirm this matches your actual account quota, see .env.example",
        )
    return CheckResult("LLM configuration", PASS, f"API key set, daily limit={config.GEMINI_DAILY_REQUEST_LIMIT}")


def _check_academic_sources_reachable() -> CheckResult:
    try:
        import httpx
    except Exception as e:  # noqa: BLE001
        return CheckResult("Academic source reachability", WARN, f"httpx import failed: {e}")
    try:
        r = httpx.get("https://api.openalex.org/works?per-page=1", timeout=10)
        if r.status_code == 200:
            return CheckResult("Academic source reachability", PASS, "OpenAlex reachable")
        return CheckResult("Academic source reachability", WARN, f"OpenAlex returned HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return CheckResult("Academic source reachability", WARN, f"OpenAlex unreachable: {type(e).__name__}")


def _check_news_sources_reachable() -> CheckResult:
    try:
        from .. import config
    except Exception as e:  # noqa: BLE001
        return CheckResult("News source reachability", WARN, f"config import failed: {e}")
    if not config.NEWS_FEEDS:
        return CheckResult("News source reachability", WARN, "NEWS_FEEDS is empty - academic-only mode")
    try:
        import httpx
        r = httpx.get(config.NEWS_FEEDS[0], timeout=10, follow_redirects=True)
        if r.status_code < 400:
            return CheckResult("News source reachability", PASS, f"first feed reachable (HTTP {r.status_code})")
        return CheckResult("News source reachability", WARN, f"first feed returned HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return CheckResult("News source reachability", WARN, f"first feed unreachable: {type(e).__name__}")


def _check_telegram_config() -> CheckResult:
    try:
        from .. import config
    except Exception as e:  # noqa: BLE001
        return CheckResult("Telegram configuration", WARN, f"config import failed: {e}")
    if not config.TELEGRAM_BOT_TOKEN and not config.TELEGRAM_CHAT_ID:
        return CheckResult("Telegram configuration", WARN, "not configured - digest will be local-only (this is fine)")
    if bool(config.TELEGRAM_BOT_TOKEN) != bool(config.TELEGRAM_CHAT_ID):
        return CheckResult("Telegram configuration", FAIL, "only one of TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID is set")
    return CheckResult("Telegram configuration", PASS, "bot token and chat ID both set")


def _check_drive_config() -> CheckResult:
    try:
        from .. import config, gdrive
    except Exception as e:  # noqa: BLE001
        return CheckResult("Google Drive configuration", WARN, f"import failed: {e}")
    if not config.GDRIVE_ENABLED:
        return CheckResult("Google Drive configuration", WARN, "disabled (GDRIVE_ENABLED=false) - this is the safe default")
    if gdrive.is_configured():
        return CheckResult("Google Drive configuration", PASS, "enabled and token present")
    return CheckResult("Google Drive configuration", FAIL, "enabled but no token - run: python -m cyber_radar.gdrive_auth")


def _check_scheduler() -> CheckResult:
    if shutil.which("systemctl"):
        return CheckResult("Scheduler", PASS, "systemd available - see systemd/*.example")
    return CheckResult("Scheduler", WARN, "systemd not found - use cron or run manually, see docs/DEPLOYMENT.md")


def _check_profiles() -> CheckResult:
    try:
        from .. import config
        from ..research import profiles as research_profiles
    except Exception as e:  # noqa: BLE001
        return CheckResult("Profile validity", FAIL, f"import failed: {e}")
    problems = []
    for pid in config.ACTIVE_RESEARCH_PROFILES:
        path = os.path.join(config.RESEARCH_PROFILES_DIR, f"{pid}.yaml")
        if not os.path.isfile(path):
            problems.append(f"'{pid}' not found at {path}")
            continue
        try:
            research_profiles.load_profile(path)
        except Exception as e:  # noqa: BLE001
            problems.append(f"'{pid}' failed to load: {e}")
    if not problems:
        return CheckResult("Profile validity", PASS, f"{len(config.ACTIVE_RESEARCH_PROFILES)} active profile(s) valid")
    return CheckResult("Profile validity", FAIL, "; ".join(problems))


def run_all_checks() -> list[CheckResult]:
    return [
        _check_python_version(),
        _check_packages(),
        _check_directories(),
        _check_disk_space(),
        _check_database(),
        _check_schema(),
        _check_profiles(),
        _check_llm_config(),
        _check_academic_sources_reachable(),
        _check_news_sources_reachable(),
        _check_telegram_config(),
        _check_drive_config(),
        _check_scheduler(),
    ]


_ICON = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌"}


def main(argv: list[str] | None = None) -> int:
    results = run_all_checks()
    for r in results:
        print(f"{_ICON[r.status]} {r.name}: {r.status}" + (f" — {r.detail}" if r.detail else ""))
    failed = [r for r in results if r.status == FAIL]
    warned = [r for r in results if r.status == WARN]
    print()
    if failed:
        print(f"Overall: FAIL ({len(failed)} failed, {len(warned)} warnings)")
        return 1
    if warned:
        print(f"Overall: PASS with warnings ({len(warned)} warnings)")
        return 0
    print("Overall: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
