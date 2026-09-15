<!--
Synthetic example output, formatted to match what `cyber-radar run`
prints to the console/log after every pipeline run (see
cyber_radar/run_pipeline.py's collector-health report and
docs/ARCHITECTURE.md "Health checks"). Not sent to Telegram - console/log
only, to avoid digest noise. No real source names, credentials, or
infrastructure details - all values below are illustrative.
-->

# Collector Health Report (example)

Run: 2026-09-15T06:00:03Z · duration: 41.2s

## News sources

| Source | Attempted | Items | Status |
|---|---:|---:|---|
| example-vendor-advisories | ✅ | 12 | OK |
| example-security-blog | ✅ | 4 | OK |
| example-research-feed | ✅ | 0 | ⚠️ anomaly: 0 results, 3rd consecutive run (last non-zero: 2026-09-12) |
| example-vuln-tracker | ❌ | — | ERROR: HTTP 503 (retried 3x) |

## Academic sources

| Source | Attempted | Items | Status |
|---|---:|---:|---|
| openalex | ✅ | 38 | OK |
| arxiv | ✅ | 21 | OK |
| semantic-scholar | ✅ | 14 | OK |
| crossref | ✅ | 9 | OK |
| datacite | ✅ | 2 | OK |

## Pipeline funnel

```
Collected (raw):        100
After deduplication:     71
After relevance filter:  19
Deep-analyzed (LLM):     19
Selected for digest:     11
```

## Budget usage (today, UTC)

| Pool | Used | Limit |
|---|---:|---:|
| News LLM budget | 6 | 20 |
| Papers LLM budget | 13 | 30 |
| Research Profile A | 2 | 10 |
| Research Profile B | 0 | 10 |

## Rate limiter (cross-process)

| API | Requests this window | Limit |
|---|---:|---:|
| arXiv | 21 | 60/min |
| Semantic Scholar | 14 | 100/5min |
| OpenAlex | 38 | 100/sec (polite pool) |

Overall: **1 source anomaly** (example-research-feed), **1 source error**
(example-vuln-tracker, transient), 0 budget overruns, 0 rate-limit
violations.
