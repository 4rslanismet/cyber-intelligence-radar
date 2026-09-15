# Sources

## News (default: empty — you configure your own)

Set `NEWS_FEEDS` in `.env` to a comma-separated list of RSS/Atom URLs.
Any standard feed works (`cyber_radar/collectors/news.py` uses
`feedparser`). No source is shipped as a hardcoded default — this keeps
the shipped defaults free of any particular vendor/publisher endorsement
and free of this project's own private feed list.

## Academic (default sources — no API key required)

| Source | Key required? | Notes |
|---|---|---|
| OpenAlex | No | Primary source; `CONTACT_EMAIL` recommended for better rate limits |
| arXiv | No | Rate limited to be considerate of the shared public API |
| Semantic Scholar | No (key optional) | `SEMANTIC_SCHOLAR_API_KEY` raises your rate limit |
| Crossref | No | |
| DataCite, OpenAIRE, OpenReview, OpenCitations | No | Used when a profile enables citation snowballing |
| DBLP | No | Disabled by default (`DBLP_ENABLED=false`) — commonly bot-blocked from cloud/VPS hosts; try enabling if your network isn't blocked |

## Optional (credential-gated, no collector shipped yet)

`cyber_radar/config.py`'s `OPTIONAL_ACADEMIC_SOURCES` names several
paid/institutional sources (IEEE Xplore, Scopus, Web of Science, Lens,
Springer Nature, CORE, and a few Scholar-proxy services) — **no
collector code exists for these yet**. If you set the corresponding API
key, the pipeline logs `disabled_missing_credentials`→ no-op; it never
pretends to query a source it can't actually reach. Contributions
implementing one of these are welcome (see `CONTRIBUTING.md`).

## Adding your own academic source

1. Add a `search(...)` function to a new module under `cyber_radar/collectors/`.
2. Wire it into `_collect_profile` in `cyber_radar/run_pipeline.py`
   (see how the existing sources are called for the pattern).
3. Add rate limiting if the source has a published limit — reuse
   `cyber_radar/collectors/academic._HostRequestLimiter` (cross-process
   safe, see [ARCHITECTURE.md](ARCHITECTURE.md)) rather than adding a new
   ad-hoc one.
