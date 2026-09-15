# Troubleshooting

Run `cyber-radar doctor` first — it catches most of the issues below
automatically with a specific PASS/WARN/FAIL per check.

## "connection failed: password authentication failed"

Your `DATABASE_URL` role/password doesn't match what PostgreSQL expects.
Re-check the role you created in [INSTALLATION.md](INSTALLATION.md) step 1.

## "papers table not found" / doctor says schema not initialized

Run `cyber-radar db init`.

## 429 / rate limit errors from Gemini on the very first run

Your `GEMINI_DAILY_REQUEST_LIMIT` is set above your account's actual
free-tier quota. Check your real limit at
https://ai.google.dev/gemini-api/docs/rate-limits and lower the value in
`.env` with margin below it.

## Hunt Opportunity / Action Required is empty

This is often correct, not a bug — these categories only fill with
items that genuinely qualify (see [ARCHITECTURE.md](ARCHITECTURE.md)
"Backfill"). Check the collector-health output printed after a run (or
`cyber-radar doctor`'s source-reachability checks) to confirm sources
are actually returning results before assuming something's broken.

## DBLP always shows `disabled_degraded_optional`

DBLP has no API key requirement but commonly blocks requests from cloud/
VPS IP ranges. This is expected and does not affect the rest of the
pipeline — `DBLP_ENABLED=false` is the default for exactly this reason.

## Telegram digest never arrives

- Confirm both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set (both
  or neither — one alone is treated as a configuration error by
  `cyber-radar doctor`).
- The digest is always written locally regardless
  (`data/reports/*.md`) — check there to confirm the run itself
  succeeded.

## Google Drive uploads fail with `invalid_grant`

Your OAuth refresh token has expired or been revoked. Re-run
`python -m cyber_radar.gdrive_auth`. If your Google Cloud OAuth consent
screen is in "Testing" publish status, refresh tokens expire roughly
every 7 days — moving it to "In production" in Google Cloud Console
removes this (a one-time manual step in Google's console, not something
this project can do for you).

## A source shows a "consecutive zero results" warning

See [ARCHITECTURE.md](ARCHITECTURE.md) "Health checks" — this means a
specific source has returned zero results for several runs in a row
(configurable via `SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT`). Check that
source's URL/availability directly.

## Still stuck

Open an issue with the output of `cyber-radar doctor` attached (it
never prints secrets, so it's safe to share).
