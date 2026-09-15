# Configuration

All configuration is via environment variables, loaded from `.env` (see
`.env.example` for the full file with defaults and inline explanations).
Every setting has a safe default except where marked **REQUIRED**.

## Database (REQUIRED)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | `postgresql://user:CHANGE_ME@your-host:port/dbname`. See [INSTALLATION.md](INSTALLATION.md). |

## LLM (REQUIRED)

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | Free key from https://aistudio.google.com/apikey |
| `RELEVANCE_MODEL` | `gemini-3.8-flash` | Cheap/fast model for the relevance filter |
| `ANALYSIS_MODEL` | `gemini-3.8-flash` | Stronger model for deep analysis |
| `GEMINI_DAILY_REQUEST_LIMIT` | `18` | **Set this below your account's real free-tier quota** ([check here](https://ai.google.dev/gemini-api/docs/rate-limits)) — a limit set above your real quota causes 429 errors starting from your first run |
| `GEMINI_RUNS_PER_DAY` | `2` | How many times per day you schedule `cyber-radar run` — the daily limit is split evenly |
| `GEMINI_MIN_CALL_INTERVAL_SECONDS` | `2.0` | Minimum spacing between LLM calls |
| `NEWS_DAILY_LLM_BUDGET` / `PAPERS_DAILY_LLM_BUDGET` | `9` / `9` | Independent budget pools so academic volume can never starve news analysis or vice versa |

## News sources

| Variable | Default | Notes |
|---|---|---|
| `NEWS_FEEDS` | empty | Comma-separated RSS/Atom URLs. Empty = academic-only mode. |

## Academic sources

| Variable | Default | Notes |
|---|---|---|
| `KEYWORDS` | `cybersecurity` | Comma-separated; each queried independently against OpenAlex/arXiv/Semantic Scholar/Crossref (no key required) |
| `CONTACT_EMAIL` | empty | Optional — identifies you to OpenAlex/Crossref's "polite pool" for better rate limits |
| `SEMANTIC_SCHOLAR_API_KEY` | empty | Optional — raises your Semantic Scholar rate limit |
| `DBLP_ENABLED` | `false` | DBLP needs no key but is commonly bot-blocked from cloud hosts |

## Telegram (optional)

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Leave both empty for local-output-only mode |

## Google Drive (optional, disabled by default)

| Variable | Default | Notes |
|---|---|---|
| `GDRIVE_ENABLED` | `false` | Opt-in — nothing is ever uploaded or deleted while false |
| `GDRIVE_OAUTH_CLIENT_ID` / `_SECRET` | empty | From a Google Cloud Console OAuth client (type: "TVs and Limited Input devices") |
| `GDRIVE_ROOT_FOLDER_ID` / `_NAME` | empty / `Cyber Intelligence Radar` | Leave ID empty to auto-create a folder by name |
| `GDRIVE_SYNC_MODE` | `direct` | `direct` = simple synchronous upload; `queued` = persistent resumable-upload queue with its own worker (recommended if you enable Drive on a resource-constrained host) |
| `GDRIVE_DAILY_UPLOAD_BUDGET_GB` / `_DAILY_FILE_LIMIT` | `5` / `500` | Only relevant in `queued` mode |

## Retention

| Variable | Default | Notes |
|---|---|---|
| `LOCAL_RETENTION_DAYS` | `2` | Local files are only ever deleted after a **confirmed** Drive upload — if Drive is disabled, nothing is ever deleted |
| `PDF_CACHE_RETENTION_DAYS` | `0` | Raw PDF cache — cleared same-run by default since text extraction happens immediately |

## Research profiles

See [PROFILES.md](PROFILES.md) for the full guide.

| Variable | Default | Notes |
|---|---|---|
| `ACTIVE_RESEARCH_PROFILES` | `daily_cyber` | Comma-separated profile IDs, loaded from `profiles/<id>.yaml` |
| `RESEARCH_PROFILE_A_ID` / `_B_ID` | empty | Assign up to two profiles their own scored digest section |
| `RESEARCH_PROFILE_A_TARGET` / `_B_TARGET` | `5` / `5` | How many papers per profile per digest |

## Operational quotas (news digest categories)

| Variable | Default |
|---|---|
| `OPERATIONAL_ACTION_TARGET` / `_HUNT_TARGET` / `_TUTORIAL_TARGET` / `_AWARENESS_TARGET` | `5` each |

These are *targets*, not hard minimums — a category shows fewer items
rather than padding with low-quality/irrelevant content.

## Academic quotas

| Variable | Default |
|---|---|
| `ACADEMIC_CURRENT_TARGET` / `_TIMELINE_TARGET` / `_HISTORICAL_TARGET` | `5` each |
| `ACADEMIC_CLASSIC_TARGET` | `1` |

## Rate limits / health checks

| Variable | Default | Notes |
|---|---|---|
| `SOURCE_ANOMALY_DROP_THRESHOLD` | `0.4` | A source dropping >40% vs. its last successful run is flagged |
| `SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT` | `3` | Escalates to a stronger warning after N consecutive zero-result runs |
| `HIGH_VALUE_VENDOR_KEYWORDS` | Microsoft, Windows, Cisco, ... | Extra priority weight for news mentioning these vendors/products — tune to your own environment |

See [ARCHITECTURE.md](ARCHITECTURE.md) for why the academic-source rate
limiter is cross-process safe by design, not just per-process.
