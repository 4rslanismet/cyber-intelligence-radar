# Quickstart

The exact path from a fresh clone to your first digest:

```bash
git clone <this-repo-url> cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cyber-radar setup      # interactive: DB URL, Gemini key, keywords, Telegram/Drive (optional)
cyber-radar doctor     # confirms everything above is actually reachable/valid
cyber-radar db init    # creates the schema (idempotent)
cyber-radar demo       # full sample digest, zero live calls - confirms rendering works
cyber-radar run        # the real thing: collects, analyzes, writes a digest
cyber-radar digest     # prints the digest you just generated
```

## What `cyber-radar run` actually does

1. Collects news from your configured RSS feeds (`NEWS_FEEDS`) and
   academic papers from OpenAlex/arXiv/Semantic Scholar/Crossref using
   your `KEYWORDS` (and any active research profile's own queries).
2. Deduplicates against what it already has.
3. Runs a cheap relevance pass, then a deeper LLM analysis pass on
   what's relevant — bounded by your daily LLM budget
   (`GEMINI_DAILY_REQUEST_LIMIT`, split into independent `NEWS_DAILY_LLM_BUDGET`/
   `PAPERS_DAILY_LLM_BUDGET` pools so one never starves the other).
4. Builds the digest sections (see [ARCHITECTURE.md](ARCHITECTURE.md)).
5. Writes it to `data/reports/YYYY-MM-DD_<slot>.md`.
6. Sends it to Telegram if configured (`TELEGRAM_BOT_TOKEN`/`_CHAT_ID`) -
   otherwise this step is a no-op, not an error.
7. Syncs to Google Drive if `GDRIVE_ENABLED=true` - otherwise nothing is
   uploaded and nothing is ever deleted locally.

## Where things land

- `data/reports/*.md` — every digest ever generated, kept locally
- `data/academic/pdf/` — downloaded open-access PDFs (if any were resolved)
- Everything above is `.gitignore`d and never touched by the repository

## Next steps

- [PROFILES.md](PROFILES.md) — steer the radar toward SOC/CTI/DFIR/your
  own custom focus
- [CONFIGURATION.md](CONFIGURATION.md) — every setting, with safe defaults
- [DEPLOYMENT.md](DEPLOYMENT.md) — run this twice a day automatically
