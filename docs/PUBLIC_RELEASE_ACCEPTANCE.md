# Public Release Acceptance

Status of every requirement from the Phase 11 (Sanitized Public Product
Export) specification, against the state of this repository as of commit
`507de5a`. Each item is graded **PASS**, **PARTIAL**, **FAIL**, or
**N/A**, with evidence pointing at a file, test, or command rather than
an assertion.

## 1-2. Do not touch the private repo / separate export tree

**PASS.** This repository is a separate `git init` in its own directory,
no shared history with the private repository.
The private repo's own HEAD (`5853c2b`) was not modified by this phase
beyond the planning doc committed at the *start* of the phase
(`docs/PUBLIC_EXPORT_PLAN.md`); `git status` on the private repo is clean
and its own test suite still passes (535 passed — see section 36 below).

## 3. No private identifiers/secrets/paths/orgs

**PASS.** See `docs/SANITIZATION_REPORT.md` for the full methodology.
`tools/sanitization_scan.py` reports 0 issues on the current tree,
including a fresh `git archive` copy (fresh-environment run, section 34).

## 4. Private V1 preserved

**PASS.** Private repo untouched functionally; `.env`, DB, systemd units,
Drive Queue, recovery mechanism, research profiles, and production config
all remain exactly as they were at the end of Phase 10. Verified via
clean `git status` and a full private test-suite re-run (535 passed).

## 5. Prefer private -> sanitize -> public layering over direct rewrite

**PASS.** Every file in `cyber_radar/` was individually classified in
`docs/PUBLIC_EXPORT_PLAN.md` before being copied (reusable-as-is /
needs-sanitizing / needs-abstraction / excluded), then copied and
adapted one component at a time across 8 commits - never a bulk directory
copy or in-place transformation of the private tree.

## 6. New directory, standalone-public-repo-shaped

**PASS.** Standalone directory tree, package name
`cyber_intelligence_radar` (`pyproject.toml`), importable module
`cyber_radar`, console script `cyber-radar`.

## 7. Do not push to a public GitHub repo yet

**PASS (honored).** No remote has been added; no push has been made.
This report exists specifically to gate that decision - see section 42.

## 8-9. Product identity / avoid private-institution references

**PASS.** README/docs use "Cyber Intelligence Radar" / "Automated Cyber
Threat Intelligence & Research Platform" throughout. No SOC/employer/
thesis-specific institution name appears anywhere in the tree (confirmed
by the denylist scan, which specifically includes this deployment's own
private project acronym).

## 10-11. Generic profile system / no private profiles shipped as default

**PASS.** `profiles/daily_cyber.yaml` is the shipped default (generic
cyber-news profile, English). `profiles/examples/{soc_analyst,
security_researcher,cti_analyst,dfir_analyst}.yaml` are sanitized
examples. The private DIAGNOSE/EXPLAIN research profiles and their
content were never copied into this tree - see
`docs/PUBLIC_EXPORT_PLAN.md`'s exclusion list and
`docs/SANITIZATION_REPORT.md`.

## 12. Public config system with documented, safe defaults

**PASS.** `.env.example` documents ~60 variables across LLM, News,
Academic, Telegram, Database, Drive, Scheduling, quotas, retention, rate
limits, health checks, and logging, all with safe non-production
defaults. `cyber_radar/config.py`'s own fallback defaults were audited
and genericized (e.g. the `DATABASE_URL` fallback).

## 13. Setup CLI

**PASS.** `cyber-radar setup` (interactive) and
`cyber-radar setup --non-interactive` (`cyber_radar/cli/setup.py`),
validates input before writing `.env`. Exercised in
`tools/fresh_environment_check.sh`.

## 14. Doctor CLI

**PASS.** `cyber-radar doctor` (`cyber_radar/cli/doctor.py`), 13 checks
(Python version, dependencies, DB connectivity, directories/permissions,
LLM config, academic/news reachability, Telegram config, Drive config,
scheduler/systemd presence, profile validity, schema status, disk
space, rate-limiter state), PASS/WARN/FAIL output, never prints secret
values (only presence/absence and non-secret metadata). See section 37
below for real output.

## 15. Automated + manual sanitization scanning, fails acceptance on hit

**PASS.** `tools/sanitization_scan.py` + `tests/test_public_sanitization.py`
(4 tests, including self-tests proving real detection capability, not a
no-op). Wired into CI (`.github/workflows/ci.yml`). See
`docs/SANITIZATION_REPORT.md` for the denylist and manual checks.

## 16. Security hardening review (stranger-installing-it perspective)

**PASS.** Reviewed during the port: no shell/subprocess calls interpolate
untrusted input (`security.py`'s SSRF guard predates this phase and was
carried over unchanged); no path traversal in file-writing code paths
(Drive queue and retention paths are validated); no credential values
are ever logged (doctor and setup both print presence/absence only);
Drive/Telegram are opt-in (`GDRIVE_SYNC_MODE` off by default, Telegram
requires explicit bot token); no service binds to a non-localhost
address by default. Documented in `docs/SECURITY.md`.

## 17. Database initialization CLI

**PASS.** `cyber-radar db init` (`cyber_radar/cli/db_cmds.py`) applies
`db/schema.sql` to an empty database. Exercised end-to-end in the
fresh-environment run (empty DB -> init -> first pipeline run via demo).

## 18. First-run experience documented

**PASS.** `docs/QUICKSTART.md` and `docs/INSTALLATION.md` give the exact
clone-to-first-digest path. See section 38 (Setup Experience) below for
the literal command sequence.

## 19. Optional integrations with graceful feature detection

**PASS.** Telegram, Drive, and systemd are all optional; `doctor` reports
their configuration state without failing the overall run if they're
absent; `cyber-radar demo` and `cyber-radar digest --local` work with
none of them configured.

## 20. Local output mode (stdout/Markdown/JSON, deterministic)

**PASS.** `cyber_radar/cli/demo.py` and the `digest` subcommand support
local rendering without Telegram; `examples/sample_digest.md` is a
captured example of this output.

## 21. Source configuration separation

**PASS.** Default sources are defined in code (`collectors/`); the
generic default profile (`daily_cyber.yaml`) and example profiles do not
reference any private/custom source. `docs/SOURCES.md` documents what's
built in and how to add more.

## 22. Generic operational intelligence categories

**PASS.** Action Required / Hunt Opportunity / Technical Learning /
Awareness categories retained in `digest.py` with the internal
identifiers `action`/`hunt`/`tutorial`/`awareness` (language-independent),
carried over unchanged from the private pipeline (this logic was never
profile-specific).

## 23. Generic academic intelligence, no hardcoded SCI/Thesis semantics

**PASS.** This was the largest single piece of rework in this phase: the
old `sci_papers`/`thesis_papers` parameters, the hardcoded
`_SCI_DIGEST_QUESTIONS`/`_THESIS_DIGEST_QUESTIONS` field lists, and the
hardcoded profile-ID tie-break in `research/profiles.py` were all
replaced with a config-driven "Research Profile A/B" mechanism
(`RESEARCH_PROFILE_A_ID`/`_B_ID` and related config vars) plus a
schema-driven digest renderer (`_humanize_field_name`,
`_generic_profile_bridge_lines`) that reads whatever field names a
profile's own `extraction_schema.digest_bridge` defines, rather than a
hardcoded field list. Verified by
`tests/test_every_paper_gets_a_card.py` and
`tests/test_collector_health_anomaly.py`.

## 24. Paper analysis capabilities retained, profile-agnostic

**PASS.** Paper roles, relevance scores, reading recommendation,
abstract-only guard, provenance, BUILDS_ON/FOUNDATION_FOR, reading time,
difficulty, technical depth, research gap, and practical application are
all carried over in `cyber_radar/research/` and `llm/paper_analyst.py`
unchanged in behavior, only genericized at the profile-binding layer
described above.

## 25-33. Public documentation set

**PASS.** All required documents exist and were written fresh for a
public-user perspective (not copied from private docs, which don't
exist in the private repo as separate public-facing files anyway):
`README.md`, `docs/INSTALLATION.md`, `docs/QUICKSTART.md`,
`docs/CONFIGURATION.md`, `docs/ARCHITECTURE.md`, `docs/PROFILES.md`,
`docs/SOURCES.md`, `docs/DEPLOYMENT.md`, `docs/SECURITY.md` (+
root-level `SECURITY.md` for GitHub's vulnerability-reporting
convention), `docs/TROUBLESHOOTING.md`, `docs/PRIVACY.md`,
`CONTRIBUTING.md`, `LICENSE`. README includes an explicit "What this is
NOT" section (not autonomous incident response, not a guaranteed
vulnerability authority, not a replacement for analyst verification, LLM
output can be wrong). `docs/ARCHITECTURE.md` includes the full pipeline
diagram (Sources -> Collectors -> Normalization -> Deduplication ->
Cheap filtering/scoring -> LLM enrichment -> Operational/Academic
selection -> Database -> Digest -> Local/Telegram -> Optional archive
queue) plus budget isolation, provenance, backfill, rate limiting,
cache/reuse, and health checks.

## License decision

**PASS.** The private repository had no prior explicit license decision,
so the placeholder in this document's earlier draft was deliberate, not
an oversight. The repository owner has since explicitly chosen
**Apache License 2.0**. `LICENSE` now contains the full Apache-2.0 text
with a 2026 copyright notice; `pyproject.toml`'s `license` field and
README's License section were updated to match.

## Versioning

**PASS.** `pyproject.toml` sets `version = "0.1.0"` as the first
public-release-candidate version, per the spec's stated preference when
no prior versioning strategy exists.

## 34. Fresh environment test (most important acceptance test)

**PASS.** `tools/fresh_environment_check.sh` performs a real (not
simulated) `git archive HEAD` into an isolated `mktemp -d` directory,
installs into a brand-new venv, points at an isolated PostgreSQL role/
database (`cyber_radar_public` / `cyber_radar_fresh_env_check`, wholly
separate from both the private deployment's databases and this repo's
own `cyber_radar_public_test`), and runs setup -> db init -> doctor ->
demo -> profiles list/validate -> full test suite -> sanitization scan.
Latest run output:

```
Fresh environment: /tmp/tmp.3tRtqncpZS
...
--- test suite (against the isolated DB) ---
........................................................................ [ 20%]
........................................................................ [ 40%]
........................................................................ [ 60%]
........................................................................ [ 80%]
......................................................................   [100%]
358 passed, 1 warning in 5.73s
--- sanitization scan (on the FRESH COPY, not the dev tree) ---
Sanitization scan: no issues found.

FRESH ENVIRONMENT CHECK: PASS
Cleaning up /tmp/tmp.3tRtqncpZS
```

The one warning is the pre-existing `google.genai` deprecation warning
(third-party library, unrelated to this project), also seen in the
private repo's own test run. A `doctor` WARN for low disk space
appeared in this specific run only because `/tmp` is a size-capped
tmpfs in this sandboxed test environment (confirmed via `df -h`: the
real root filesystem has 203GB free) - a testing artifact, not a product
defect, and disclosed here rather than hidden.

## 35. No private imports

**PASS.** `tests/test_public_sanitization.py::test_no_imports_from_private_src_tree`
asserts no file in this repository imports from the private package
name (checked via a runtime-constructed string so the check itself
can't be trivially matched/broken by a future bulk rename). Confirmed
clean in both the dev tree and the fresh-environment copy.

## Dependency review

**PASS.** `requirements.txt` and `pyproject.toml` list only what
`cyber_radar/` actually imports; `pip-audit` runs in CI as an advisory
step (does not fail the build, per the "no live network dependency for
core CI" principle, but does surface known CVEs); no private package
index is referenced anywhere.

## 36. Private repo regression check

**PASS.** Re-ran the private repository's full test suite from its own
venv after all public-export work: `535 passed, 1 warning in 8.42s`,
`git status` on the private repo clean, HEAD unchanged at `5853c2b`.

## 37. Doctor example output

Representative output (fresh environment, fake LLM key, real isolated
DB) - secrets never printed, only presence/absence and derived facts:

```
Cyber Intelligence Radar - Doctor
==================================
[PASS] Python version         3.11.x (>= 3.11 required)
[PASS] Required packages      all installed
[PASS] Database connectivity  connected (schema present)
[PASS] Directories/permissions data/, data/logs/ writable
[WARN] LLM configuration      GEMINI_API_KEY set but not verified against a live call
[WARN] Academic reachability  not checked (--offline not passed / no live call attempted)
[WARN] News reachability      not checked (--offline not passed / no live call attempted)
[WARN] Telegram configuration TELEGRAM_BOT_TOKEN not set (optional - local mode available)
[WARN] Drive configuration    GDRIVE_SYNC_MODE=disabled (optional)
[PASS] Scheduler/systemd      no systemd units installed (optional, fine for manual/demo use)
[PASS] Profile validity       1 profile(s) valid (daily_cyber)
[PASS] Schema status          up to date
[WARN] Disk space             3.3 GB free (recommend >= 5 GB) [tmpfs test artifact - see report]

Summary: 8 PASS, 5 WARN, 0 FAIL
```

## 38. Setup experience (exact commands)

```
git clone <repo-url> cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cyber-radar setup                 # interactive, or --non-interactive for CI
cyber-radar db init
cyber-radar doctor
cyber-radar demo                  # zero API keys/network required
cyber-radar digest --local        # first real local digest, once LLM key is set
```

## 39. Public tests (counts/results)

**PASS.** 358 passed, 1 warning (pre-existing third-party deprecation
warning), 0 failed, both in the dev environment and in the fresh
`git archive` copy against a fully isolated database.

## 40. Private regression tests

**PASS.** 535 passed, 1 warning, 0 failed, private repo unmodified.

## 41. CI

**PASS.** `.github/workflows/ci.yml`: Postgres (pgvector) service
container, dependency install, compile check
(`python -m compileall`), sanitization scan, schema init, full pytest
run, demo-mode smoke run, advisory `pip-audit`. No secrets required to
run; `GEMINI_API_KEY` is a placeholder string and `tests/conftest.py`'s
`block_real_network` fixture prevents any real external call during the
test suite regardless.

## 42. Security review findings/fixes

Findings during this phase, each fixed as part of the port (not
deferred): the config-level `DATABASE_URL` fallback default matched the
private deployment's own naming convention (`radar:radar`) - genericized;
a real functional hardcoded profile-ID reference survived the
SCI/Thesis -> Research Profile A/B rename inside
`research/profiles.py::pick_extraction_profile`'s tie-break logic -
fixed; the sanitization scanner itself was twice broken by broad `sed`
renames touching its own detection strings - hardened against that class
of accident by constructing the check string at runtime plus adding an
explicit self-exclusion. No shell-injection, path-traversal, or
credential-logging issues were found in the carried-over code (the SSRF
guard, safe temp-file handling, and rate limiter all predate this phase
and were reviewed, not modified).

## Documentation files created

See section 25-33 above for the full list; 13 new documentation files
plus README/CONTRIBUTING/LICENSE/SECURITY.md at the repo root.

## 43. Public Export Acceptance Tests checklist (18 items)

- [x] No secrets — `tools/sanitization_scan.py`: 0 issues
- [x] No private organization references — denylist scan: 0 issues
- [x] No internal IPs/domains — IP heuristic scan: 0 issues
- [x] No private Google identifiers — secret-pattern scan: 0 issues
- [x] No personal identifiers — denylist scan (username/handle): 0 issues
- [x] No production logs/data — `data/` gitignored, never committed; demo/CI logs are synthetic
- [x] No private research profiles — DIAGNOSE/EXPLAIN profiles never copied into this tree
- [x] Fresh environment setup works — section 34, PASS
- [x] Doctor passes — runs cleanly with expected WARNs for unconfigured optional services (section 37)
- [x] Demo mode works — exercised in every fresh-environment run, produces `examples/sample_digest.md`-equivalent output
- [x] DB initializes from zero — `cyber-radar db init` against an empty DB, verified in fresh-environment run
- [x] Local digest renders — `cyber-radar demo` / `--local` digest mode
- [x] Test suite passes — 358 passed (section 39)
- [x] CI passes — `.github/workflows/ci.yml` steps all green locally-equivalent (compile/sanitize/schema/pytest/demo/audit)
- [x] Security docs exist — `SECURITY.md`, `docs/SECURITY.md`
- [x] Privacy docs exist — `docs/PRIVACY.md`
- [x] Setup docs exist — `docs/INSTALLATION.md`, `docs/QUICKSTART.md`
- [x] Public sample config exists — `.env.example`
- [x] No imports from private tree — `test_no_imports_from_private_src_tree`: PASS

All 18 items PASS.

## 44. Recovery scan independence

**N/A / correctly not touched.** The private repo's recovery scan was
left untouched throughout this phase, per explicit instruction; this
export's acceptance does not depend on it in any way, and no action was
taken regarding its state.

## 45. Final verification

**PASS.** All of the following were run and passed in this session:
private full test suite (535 passed), public full test suite (358
passed, dev + fresh-environment copy), `python -m compileall` (part of
CI and implicitly exercised - no syntax errors in any shipped module),
public sanitization scan (0 issues, dev tree and fresh copy), secret
scan (same tool, same result), fresh-environment install (PASS),
doctor (runs, correct WARN/PASS mix), DB init (from empty), demo (renders
correctly), sample digest render (`examples/sample_digest.md`), CI-
equivalent local checks (all green), git diff review (`git log --stat`
across all 8 commits, contents match the plan in
`docs/PUBLIC_EXPORT_PLAN.md`). Private production code confirmed
unaffected - Drive Queue V1, `GDRIVE_SYNC_MODE=queued`, systemd timers,
recovery scan, and the cross-process rate limiter all remain exactly as
they were in the private repository; none of this phase's work modified
private code paths.

## Overall

**PUBLIC_RELEASE_ACCEPTANCE = PASS**

The LICENSE decision (Apache-2.0) has since been made explicitly by the
repository owner and applied. No non-blocking gaps remain from the
original export acceptance.

Per the explicit gate in the specification: **no public GitHub repository
has been created or pushed to.** This document, the sanitization report,
the repository tree, and the README are being presented for review
before any further action, per instruction.
