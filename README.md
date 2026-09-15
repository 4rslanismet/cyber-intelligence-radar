# Cyber Intelligence Radar

**Automated Cyber Threat Intelligence & Research Platform.**

Cyber Intelligence Radar is a self-hosted pipeline that collects
cybersecurity news and academic papers on a schedule, deduplicates and
scores them, enriches them with an LLM, and produces a structured digest
— locally, and optionally via Telegram. It also supports pluggable
"research profiles" so you can steer collection and scoring toward your
own area of focus (SOC operations, threat intelligence, DFIR, academic
research, or a custom profile you define).

## What it does

- Collects security news (RSS/Atom) and academic papers (OpenAlex,
  arXiv, Semantic Scholar, Crossref, and more — all free, no API key
  required for the core sources)
- Deduplicates events and papers across sources
- Filters for relevance with a cheap LLM pass, then deep-analyzes
  relevant items with a stronger model
- Splits news into four independent, config-driven operational
  categories: 🚨 Action Required, 🕵️ Hunt Opportunity, 📚 Technical
  Learning, 👀 Awareness
- Builds an academic reading list: Current papers, a chronological
  Foundation→Current learning path, a daily Classic pick, Historical
  highlights, and up to two custom "Research Profile" sections
- Supports custom research profiles (see [docs/PROFILES.md](docs/PROFILES.md)) —
  ship your own concept groups, queries, and scoring rubric without
  touching the code
- Tracks reading state and surfaces a single algorithmically-scored
  "Read Now" recommendation
- Generates a digest as a local Markdown file, and optionally sends it
  to Telegram
- Optionally archives generated reports/exports/backups to Google Drive
  via a resumable, budget-aware upload queue
- Runs a cross-process-safe rate limiter for external academic APIs, a
  collector-health report, and per-source anomaly detection out of the box

## What it is NOT

- **Not an autonomous incident-response system.** It produces
  intelligence and reading material for a human analyst — it does not
  take action on your infrastructure.
- **Not a guaranteed vulnerability authority.** CVE/KEV/CVSS data is
  extracted from source text and cross-referenced where possible, but
  always verify against the vendor advisory or NVD/CISA KEV directly
  before acting.
- **Not a replacement for analyst judgment.** LLM output can be wrong,
  incomplete, or miss nuance. Structured claims (severity, IOC,
  technique mapping) should be treated as a starting point for
  verification, not a final answer.

## Quickstart

```bash
git clone <this-repo-url> cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cyber-radar setup      # interactive - writes .env
cyber-radar doctor     # verify your configuration
cyber-radar db init    # create the database schema
cyber-radar demo       # see a full sample digest - no API keys/network/DB needed
cyber-radar run        # run the radar for real
```

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the full walkthrough and
[docs/INSTALLATION.md](docs/INSTALLATION.md) for prerequisites (PostgreSQL,
a free Gemini API key).

## Documentation

| File | Covers |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Prerequisites, one-time setup |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Clone-to-first-digest walkthrough |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `.env` setting explained |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline design, data flow, budget isolation |
| [docs/PROFILES.md](docs/PROFILES.md) | Writing and activating research profiles |
| [docs/SOURCES.md](docs/SOURCES.md) | News/academic sources, adding your own |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | systemd, cron, Docker |
| [docs/SECURITY.md](docs/SECURITY.md) → also see top-level [SECURITY.md](SECURITY.md) | Secrets, least privilege, safe deployment |
| [docs/PRIVACY.md](docs/PRIVACY.md) | What data leaves your system and to whom |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Status

This is a `0.1.0` public preview derived from a private, production
single-operator deployment (see [docs/PUBLIC_RELEASE_ACCEPTANCE.md](docs/PUBLIC_RELEASE_ACCEPTANCE.md)
for the full export/acceptance record). The core pipeline, Drive Queue,
rate limiting, and research-profile mechanism are the same code that
runs daily in that deployment. The CLI, packaging, and public
documentation are new for this release. See
[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for what's not
yet included.

## License

[Apache License 2.0](LICENSE).
