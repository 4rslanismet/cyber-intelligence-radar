# Security (technical detail)

See the top-level [SECURITY.md](../SECURITY.md) for how to report a
vulnerability. This file covers deployment-level security detail.

## Secrets management

- All secrets (Gemini API key, Telegram bot token, Drive OAuth client
  secret, database password) live only in `.env`, which is `.gitignore`d
  and never read by any code path other than `python-dotenv` at process
  start.
- `cyber-radar setup` writes `.env` with mode `0600`.
- `cyber-radar doctor` never prints a secret value — only whether one is
  set/reachable.
- No secret is ever logged. If you add a new integration, follow the
  same rule: log the config variable *name*, never its value.

## Least privilege

- The database role you create for this project only needs privileges
  on its own database (see [INSTALLATION.md](INSTALLATION.md)) — it does
  not need superuser.
- Run the scheduled job as a dedicated, unprivileged system user (see
  [DEPLOYMENT.md](DEPLOYMENT.md)'s systemd hardening baseline), never as
  root.
- The Google Drive integration uses OAuth scope
  `drive.file` (access only to files it created), not full Drive access.

## SSRF protection

RSS feed fetching and PDF downloads both go through
`cyber_radar/security.py`'s `is_safe_external_url()`, which blocks
non-HTTP(S) schemes and literal loopback/private/link-local/cloud-
metadata IP addresses before any request is made. **Known limitation:**
this does not defend against DNS rebinding (re-resolving a hostname to a
private IP after the initial check) — if you configure feeds from
sources you don't fully trust, be aware of this gap.

## Prompt injection

Every LLM prompt that processes external, untrusted content (news
articles, paper abstracts/full text) includes an explicit
prompt-injection-resistance instruction block, in addition to
structural grounding checks (see [ARCHITECTURE.md](ARCHITECTURE.md)
"Provenance and hallucination guards") that mechanically verify
extracted structured data against the source text rather than trusting
the model's claims.

## Telegram

The feedback listener (`cyber_radar/telegram_listener.py`) checks every
inbound update against your configured `TELEGRAM_CHAT_ID` before acting
on it. **Known limitation:** this is a single hardcoded chat ID, not a
configurable multi-user allowlist — if you need multiple authorized
users, you'll need to extend this check yourself for now (see
`docs/ARCHITECTURE.md` "Not included").

## Google Drive

- Disabled by default (`GDRIVE_ENABLED=false`).
- Uploads are restricted to an explicit allowed-roots list
  (`cyber_radar/drive_queue.py`'s exfiltration guard) — only files under
  `data/reports`, `data/db_backups`, `data/research`,
  `data/academic/pdf` can ever be queued, and symlinks are rejected by
  default.
- A local file is only ever deleted after its Drive upload is
  **confirmed** (fresh remote metadata check, not just a 200 response) —
  any exception before that point means the file is never deleted.

## Dependency scanning

Run `pip-audit` (or your preferred scanner) against `requirements.txt`
before deploying, and periodically thereafter. This is included in CI
(see `.github/workflows/ci.yml`).

## Safe systemd deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the hardening baseline used in
the provided unit templates, and what's deliberately not enabled
(`ProtectSystem`/`ProtectHome`/`ReadWritePaths`) until you've audited
your own deployment's actual write paths.

## Network exposure

This project does not run a network-listening service by default (no
web UI, no API server) — the only network activity is outbound (to
LLM/news/academic APIs, Telegram, Drive). If you build a web UI or API
on top of this, bind it to `localhost` by default and require explicit
configuration to expose it more broadly.
