# Sanitization Report

Covers what was checked before this repository was assembled from the
private deployment it was derived from, how it was verified, and what
residual risk remains. No actual private/secret value is reproduced
anywhere in this report — only the classes of data checked and the
mechanism used.

## What classes of private data were checked

Per the export instructions, the following were explicitly checked for:

- Organization names, internal hostnames/domains, internal IP addresses
- Usernames, home directory paths, institution names
- API keys, tokens, passwords, credentials (any form)
- Production Google Drive folder IDs / OAuth client credentials
- Telegram bot tokens / chat IDs
- System-specific identifiers, environment-specific systemd paths
- Private research notes, private research profile contents
  (the DIAGNOSE/EXPLAIN research direction, and the two profile YAML
  files defining it, were never copied into this tree at all — see
  `docs/PUBLIC_EXPORT_PLAN.md`)
- Recovery/archive data, production database contents, internal
  operational logs, commit leftovers

## Automated scanning

`tools/sanitization_scan.py` (also wired into `tests/test_public_sanitization.py`
and CI) scans every tracked file for:

1. **Secret-shaped patterns**: Google API keys (`AIza...`), Google OAuth
   client secrets (`GOCSPX-...`), Telegram bot tokens, generic
   OpenAI-style keys, PEM private key blocks, AWS access key IDs, and
   any connection-URL credential that doesn't look like an obvious
   placeholder (`CHANGE_ME`, `test`/`ci_`/`demo`/`example`/`fake`/
   `placeholder`-containing, or `<...>`-bracketed).
2. **A denylist of known-private, non-secret identifiers**: this
   deployment's username, hostname, GitHub handle, and an internal
   project acronym. These are not secrets themselves — they're canary
   strings that would only appear here via an accidental copy-paste from
   the private repository.
3. **Private/internal-looking IP addresses**: RFC1918 ranges and
   link-local, excluding common textbook/documentation example IPs
   (`192.168.1.1`, `10.0.0.1`, etc.) and the well-known public
   cloud-metadata address (used as a documented SSRF-guard constant, not
   a real host of ours) to avoid false positives.

The scanner has self-tests proving it actually detects an injected
marker/secret (not a no-op) — see
`tests/test_public_sanitization.py::test_scanner_actually_detects_injected_private_marker`
and `::test_scanner_detects_injected_secret_pattern`.

A separate check (`test_no_imports_from_private_src_tree`) confirms no
code in this repository imports from the private repository's package
name.

**Current result: 0 issues found** (`tools/sanitization_scan.py` exit
code 0), including on a fresh `git archive` copy of the committed tree
via `tools/fresh_environment_check.sh` — see
`docs/PUBLIC_RELEASE_ACCEPTANCE.md` section 34 for that run's output.

## Manual checks performed

- Read every copied source file's diff against the private original
  before committing (not a blind bulk copy) - see
  `docs/PUBLIC_EXPORT_PLAN.md` for the explicit reusable/sanitize/
  abstract/exclude classification made before any file was copied.
- Grepped the private `db/schema.sql` for the two private research
  profile IDs before adapting it — found only comment-level example
  references (not the actual research content) and removed/genericized
  those.
- Manually reviewed `cyber_radar/config.py`'s every default value for
  private-deployment-specific numbers/hosts (found and fixed: the
  code-level `DATABASE_URL` fallback default used the private
  deployment's own role-naming convention `radar:radar` — changed to a
  clearly generic `cyber_radar:CHANGE_ME` placeholder even though the
  original wasn't itself a real secret).
- Manually reviewed `run_pipeline.py`/`digest.py` for the SCI/Thesis ->
  Research Profile A/B rename's completeness (hardcoded profile-ID
  tie-break logic in `research/profiles.py::pick_extraction_profile`
  was found and fixed during this pass — it referenced the literal
  private profile IDs even after the rest of the rename was done).
- Manually verified `systemd/*.example` unit files use placeholder
  paths (`/opt/cyber-intelligence-radar`) and a placeholder service
  user (`cyber-radar`), not the private deployment's actual path/user.
- Confirmed `.env`/`data/` are `.gitignore`d and were never committed
  (verified via `git status`/`git log` on this repository, which has no
  history prior to this export - there is nothing to have leaked into).

## Known false positives resolved during this pass

- `tests/test_security_ssrf_guard.py`'s illustrative RFC1918-range test
  fixtures (used to exercise the SSRF guard's blocklist logic) —
  legitimate test data, not a leaked address. The IP heuristic is
  scoped to exclude `tests/`.
- The scanner's own source, and `tools/fresh_environment_check.sh`'s own
  private-path grep pattern, necessarily *mention* the identifiers
  they're built to detect — both are explicitly excluded from
  self-scanning (with a code comment explaining why, and a runtime-
  string-concatenation trick in the test file so a future blind
  find-and-replace pass can't silently break the check).
- CI/test-fixture connection-string passwords (`ci_test_password`,
  `public_test_pw`) — recognized as safe placeholders by the
  URL-credential check's marker list.

## Static security scan (bandit) — reviewed findings

`bandit -r cyber_radar` was run as part of the pre-publish gate (this is
a static-analysis tool, distinct from the sanitization scanner above,
and checks for insecure *code patterns* rather than leaked data). One
real, trivially-fixable finding was fixed: `hashlib.md5()` in
`drive_worker.py` now passes `usedforsecurity=False` (it computes a
Drive-API-compatible content checksum for integrity comparison, not a
cryptographic hash — Google Drive's own `md5Checksum` file field forces
MD5 specifically, so the algorithm itself can't change).

All other findings were reviewed and are not vulnerabilities in this
codebase's actual usage, so they were left as-is rather than changed
for the sake of a clean scan:

- **B608 (SQL built with an f-string), 9 occurrences** in
  `run_pipeline.py` and `telegram_listener.py`: every interpolated
  identifier (`table`, `field`, `shown_col`, the comparison `op`) is
  drawn from a small, hardcoded, closed set of literal strings in the
  code itself (e.g. `table = "papers" if prefix == "p" else
  "news_events"`) — never from raw user/Telegram/HTTP input. All actual
  *values* are passed as separate, properly parameterized query
  arguments. Bandit's B608 rule flags any f-string used to build a SQL
  string regardless of what's interpolated; it cannot distinguish
  "a value from a 2-element hardcoded list" from "raw external input."
- **B314/B405 (`xml.etree.ElementTree` for arXiv API responses)**:
  arXiv's Atom API is fetched over HTTPS; ElementTree's classic
  XXE/entity-expansion risks apply to untrusted XML from an
  unauthenticated/arbitrary source, which this is not. Still a
  reasonable future hardening item — noted in `docs/KNOWN_LIMITATIONS.md`
  as a candidate for switching to `defusedxml` — not done in this pass
  to avoid adding a new dependency without a separate explicit decision.
- **B603/B607 (subprocess call, partial executable path), 2 occurrences**
  in `db_backup.py` (`pg_dump`) and `notify_failure.py` (`journalctl`):
  both call `subprocess.run` with a literal argument list (never
  `shell=True`, never string-interpolated from external input).
- **B110 (bare `except: pass`), 2 occurrences**: both are intentional
  best-effort paths (a failure-notification's own log tail, and an
  optional DOAJ cross-check) already annotated in-line with why swallowing
  the exception is correct there.
- **B311 (non-cryptographic `random.uniform`)**: retry-jitter timing, not
  security-sensitive.
- **B105 (`hardcoded_password_string`)**: a false positive — the
  matched string is an OAuth token *endpoint URL*
  (`https://oauth2.googleapis.com/token`), not a credential.

## Remaining risks (disclosed, not hidden)

- **The scanner is a heuristic, not a formal proof.** It catches the
  classes of data explicitly checked above; a sufficiently unusual or
  obfuscated leak could still evade regex-based detection. Re-run it
  after any future change that copies more code from the private
  deployment.
- **Turkish-language code comments remain** in several reused source
  files (see `docs/KNOWN_LIMITATIONS.md`) — none contain secrets or
  private identifiers (verified by this scan), but they do reveal that
  this project's original development was conducted in Turkish. This
  was judged not a privacy/security issue (it's not personally
  identifying beyond what's already disclosed in this document) and is
  disclosed rather than hidden.
- **No exhaustive manual line-by-line review of every copied file** was
  performed beyond the targeted checks above plus the automated scan -
  for a codebase this size, the automated scanner plus the explicit
  allowlist-based copy process (never a blanket directory copy) is the
  practical, disclosed standard applied here.
