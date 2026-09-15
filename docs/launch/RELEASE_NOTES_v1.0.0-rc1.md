# Release Notes — v1.0.0-rc1 (Draft, NOT published)

*Drafted for `gh release create v1.0.0-rc1 --notes-file ...` or pasting
directly into the GitHub Release UI. The tag/release has deliberately
not been created — see `docs/launch/LAUNCH_CHECKLIST.md`.*

---

## Cyber Intelligence Radar v1.0.0-rc1

First public release candidate. This is the public, sanitized export of
a private, production single-operator deployment that has been running
this pipeline daily — see
[docs/PUBLIC_RELEASE_ACCEPTANCE.md](../PUBLIC_RELEASE_ACCEPTANCE.md) for
the full export/acceptance record.

**It does not just ask "Is this new?" — it asks "What actually
changed?"**

### 🔁 Material Change Detection

The same underlying event (a CVE, an incident) is tracked across runs
and only re-surfaced when something material actually happens to it —
a KEV listing, a new IOC, confirmed active exploitation, or a fix
shipping — not every time a source re-publishes the same content.
Deterministic, mechanically-checked rules (`cyber_radar/dedup.py::is_material_news_update`),
not an LLM judgment call. Worked example:
[examples/output/sample_material_update.md](../../examples/output/sample_material_update.md).

### 🎯 Personalized Relevance

Operational news is split into four independent categories per reader —
🚨 Action Required, 🕵️ Hunt Opportunity, 📚 Technical Learning,
👀 Awareness — and academic relevance is scored against your own
configured research profiles rather than a one-size-fits-all feed.

### 🔍 Evidence-First Analysis

Structured claims the LLM extracts (CVE IDs, IOCs, CWE mappings) are
mechanically re-checked against the original source text after
generation. A claim that doesn't literally appear in the source is
dropped before it ever reaches the digest or the database — a second,
independent guard on top of prompt-level instructions, not a
replacement for them.

### 📰📚 News + Academic Intelligence

One pipeline covers operational security news and academic literature
side by side: a reading list with Current papers, a chronological
Foundation→Current learning path, a daily Classic pick, Historical
highlights, and up to two custom Research Profile sections — sharing
collection/dedup/relevance infrastructure with the news side, but with
independent LLM budgets so neither starves the other.

### 🏠 Self-hosted / configurable profiles

Runs entirely on infrastructure you control. Profiles are plain YAML
(`profiles/examples/`: SOC Analyst, Security Researcher, CTI Analyst,
DFIR Analyst) — no code change needed to steer source relevance or add
a scored digest section. Telegram and Google Drive archiving are
optional and disabled by default.

### 🔒 Security / testing

- No bundled credentials; every setting documented in `.env.example`
  with safe, non-production defaults
- SSRF protections, bounded downloads, secret redaction in
  `doctor`/`setup` output
- Pre-release security gate: `pytest` (358 passed), `compileall`,
  a dedicated public-sanitization scanner, `gitleaks` (0 leaks across
  full git history), `bandit` (0 High-severity findings), `pip-audit`
  (no known vulnerabilities) — all wired into CI
  ([.github/workflows/ci.yml](../../.github/workflows/ci.yml))
- Full findings and reviewed false-positives documented in
  [docs/SANITIZATION_REPORT.md](../SANITIZATION_REPORT.md)

### Getting started

```bash
git clone https://github.com/4rslanismet/cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cyber-radar setup && cyber-radar doctor && cyber-radar db init
cyber-radar demo   # zero API keys/network needed
```

### Breaking changes

None — this is the first public release.

### Known limitations (disclosed honestly, not hidden)

- **Not included in this release**: systematic literature-review
  workflow (PRISMA-style screening), historical recovery/backfill
  tooling, NotebookLM export, spaced repetition, weekly/monthly digest
  rollups, hourly CISA KEV watch, DB backup/restore CLI. None were
  excluded for security/privacy reasons — only to keep this release's
  reviewable surface area manageable. All are reasonable candidates for
  a future release; see [ROADMAP.md](../../ROADMAP.md).
- **Mixed-language output**: some digest labels and internal code
  comments are still in Turkish (this project's original development
  language). Functionally nothing is affected — this is a cosmetic/i18n
  gap. Contributions translating remaining strings are welcome.
- **SSRF guard has no DNS-rebinding protection**: it checks the literal
  IP a hostname resolves to at request time, not resolution changes
  between check and use.
- **Telegram supports a single-user allowlist only** — `TELEGRAM_CHAT_ID`
  is one hardcoded ID, not a configurable multi-user list.
- **No local/offline LLM option** — analysis steps require the Gemini
  API; no local-model fallback yet.
- **No Docker image yet** — evaluated and deliberately postponed rather
  than shipping something unverified.
- **XML parsing (`xml.etree`) is not hardened with `defusedxml`** —
  assessed as low-risk on modern Python, but not a hardened guarantee.

Full detail on all of the above: [docs/KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).

### This is a release *candidate*

"rc1" is intentional — this is the first time this codebase has been
run outside its original single-operator deployment. If you hit a rough
edge during setup, please open an issue
([.github/ISSUE_TEMPLATE/](../../.github/ISSUE_TEMPLATE/)) rather than
assuming it's expected.

### What it is NOT

Not an autonomous incident-response system, not a guaranteed
vulnerability authority, not a replacement for analyst judgment — see
the README's "What it is NOT" section. Not a replacement for a full
Threat Intelligence Platform such as MISP or OpenCTI — see
[docs/COMPETITOR_LANDSCAPE.md](../COMPETITOR_LANDSCAPE.md).

**License:** Apache-2.0. **Full changelog:** this is the initial commit
history of the public repository — see the commit log for the complete
export/hardening/launch-prep history.
