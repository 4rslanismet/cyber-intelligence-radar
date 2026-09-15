# Privacy

What data leaves your system, and to whom, depending on what you enable.

## Always (core pipeline)

- **News feed URLs and academic search keywords** you configure are sent
  to the respective public APIs (OpenAlex, arXiv, Semantic Scholar,
  Crossref, and whichever RSS feeds you add) as ordinary search/fetch
  requests — the same as visiting those URLs in a browser.
- **Article/paper text you've collected is sent to Google's Gemini API**
  for relevance filtering and deep analysis. This is the core mechanism
  of the project — there is no fully-local mode for this step in this
  release (see "Running more privately" below).

## If Telegram is enabled

- Your digest content (including any article/paper text excerpts,
  titles, and your own notes/feedback) is sent to Telegram's servers to
  be delivered to your configured bot/chat.

## If Google Drive is enabled

- Generated reports, NotebookLM exports, and database backups are
  uploaded to your own Google Drive, using an OAuth token scoped to
  `drive.file` (files this app created — not your whole Drive).

## What is never sent anywhere by this project

- Your database contents are never transmitted except via the two
  opt-in integrations above (Drive backup upload, if enabled).
- Your `.env`/secrets are never transmitted anywhere.
- Nothing is sent to any analytics, telemetry, or usage-tracking service
  — this project has none.

## Running more privately

- Leave Telegram and Google Drive disabled (both are opt-in, disabled
  by default) — the digest is still written locally as a Markdown file.
- The LLM analysis step (Gemini API) is not currently swappable for a
  local model in this release. If you need a fully local pipeline,
  you would need to point `cyber_radar/llm/client.py` at a local
  model server yourself — this is not built in yet (contributions
  welcome, see `CONTRIBUTING.md`).
- Restrict `NEWS_FEEDS`/`KEYWORDS` to sources whose data-handling
  practices you're comfortable with — this project doesn't filter or
  vet third-party API/feed privacy policies for you.

## Data retention

See [CONFIGURATION.md](CONFIGURATION.md) "Retention" — locally generated
files are only ever deleted after a **confirmed** upload to Drive; if
Drive is disabled, nothing is ever automatically deleted.
