# Known Limitations

Honest, current gaps in this public release — not hidden, not silently
worked around.

## Not included in this release

See [ARCHITECTURE.md](ARCHITECTURE.md) "Not included" for the full list
(systematic literature review workflow, historical recovery/backfill
tooling, NotebookLM export, spaced repetition, weekly/monthly digest
rollups, hourly CISA KEV watch, DB backup/restore CLI). None were
excluded for security/privacy reasons — only to keep this release's
surface area reviewable. See `docs/PUBLIC_RELEASE_ACCEPTANCE.md` for the
full export decision record.

## Mixed-language output

Some digest labels and internal code comments are in Turkish (this
project's original development language) rather than fully translated
to English. This was a deliberate, disclosed scope decision for this
release rather than a silent gap — translating the full digest-rendering
vocabulary across the codebase is a substantial undertaking that wasn't
completed for `0.1.0`. Functionally nothing is affected; this is a
cosmetic/i18n gap. Contributions translating remaining strings are
welcome.

## SSRF: no DNS-rebinding protection

See [SECURITY.md](SECURITY.md) — the SSRF guard checks the literal IP a
hostname resolves to at request time, but doesn't defend against a
hostname changing its resolution between check and use.

## Telegram: single-user allowlist only

See [SECURITY.md](SECURITY.md) — `TELEGRAM_CHAT_ID` is a single
hardcoded ID, not a configurable multi-user allowlist.

## No local/offline LLM option

See [PRIVACY.md](PRIVACY.md) — the relevance/analysis steps require the
Gemini API; there's no built-in local-model fallback in this release.

## No Docker support yet

See [DEPLOYMENT.md](DEPLOYMENT.md) — evaluated and deliberately
postponed rather than shipping an unverified Dockerfile.

## XML parsing not hardened with `defusedxml`

Assessed as low-risk on modern Python (which disables external entity
resolution by default in `xml.etree` since 3.7.1+) but not a
zero-risk guarantee — a defense-in-depth improvement, not yet applied.
