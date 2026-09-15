# Contributing

Thanks for considering a contribution.

## Before you start

- For anything beyond a small fix, open an issue first describing what
  you want to change and why — this avoids wasted work on both sides.
- See `docs/ARCHITECTURE.md` "Not included" and `docs/KNOWN_LIMITATIONS.md`
  for known gaps that are genuinely welcome as contributions (a new
  academic source collector, DNS-rebinding-resistant SSRF protection, a
  multi-user Telegram allowlist, Docker support, i18n).

## Development setup

```bash
git clone <this-repo-url>
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # edit as needed for local testing
```

## Running tests

```bash
pytest -q
python -m compileall cyber_radar tests tools
python tools/sanitization_scan.py
```

Tests requiring a real database are automatically skipped (not failed)
if `TEST_DATABASE_URL` (or a `_test`-suffixed database derived from your
`DATABASE_URL`) isn't reachable — see `tests/conftest.py`. Tests never
touch your real/production database, and never make real network calls
(`tests/conftest.py`'s `block_real_network` fixture raises if an
un-mocked `httpx.get`/`.post` is attempted).

## Before opening a PR

- Run the full test suite and `tools/sanitization_scan.py` — both must
  be clean.
- Never commit a real secret, even in a test fixture or example — use
  obviously-fake placeholder values.
- If you touch `db/schema.sql`, use `CREATE TABLE IF NOT EXISTS` /
  `ADD COLUMN IF NOT EXISTS` — there's no migrations tool, schema
  changes must be additive and idempotent.
- Keep PRs focused — one logical change per PR is easier to review than
  a bundle of unrelated fixes.

## Code style

No enforced formatter is configured yet. Match the existing style in the
file you're editing. Prefer explicit, deterministic logic over LLM calls
wherever a rule can decide something — see the "hallucination guard"
pattern throughout `cyber_radar/dedup.py`/`llm/news_analyst.py` for the
project's general philosophy: never let the LLM decide something a
mechanical check can verify.

## Adding a source

News sources are RSS/Atom feeds configured via `NEWS_FEEDS` (see
`docs/SOURCES.md`) — no code change needed for most feeds. Adding a new
*kind* of academic source (beyond the OpenAlex/arXiv/Semantic
Scholar/Crossref/DataCite/DOAJ/OpenAIRE/OpenReview collectors already in
`cyber_radar/collectors/`) means adding a new collector module following
the existing ones' shape (fetch → normalize into the common paper/event
dict shape → return). Open an issue first if you're proposing a source
that needs new normalization logic, not just a new feed URL.

## Creating a profile

See `docs/PROFILES.md` and `profiles/examples/` — a profile is a YAML
file, no code change required. If your profile needs new digest-bridge
fields, the renderer is schema-driven (see
`cyber_radar/digest.py::_humanize_field_name`), so most new fields just
work; open an issue if you hit a case that doesn't.

## Adding domain support (beyond cybersecurity)

The pipeline's collection/dedup/material-change/relevance logic isn't
inherently cyber-specific — the domain-specific parts are the news
analyst prompt (`cyber_radar/llm/news_analyst.py`) and the default
profile (`profiles/daily_cyber.yaml`). Extending to another domain is a
reasonable contribution; open an issue describing the target domain
before starting, since it likely needs a new analyst prompt and a
domain-appropriate default profile rather than just config changes.

## Reporting bugs / proposing features / requesting a source

Use the issue templates (`.github/ISSUE_TEMPLATE/`) when opening a new
issue — bug report, feature request, or source request. For a security
vulnerability, see [SECURITY.md](SECURITY.md) instead of a public issue.
