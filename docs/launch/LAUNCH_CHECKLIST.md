# Launch Checklist

Tracks readiness for the visibility-first public launch. Publishing
actions (marked below) require explicit maintainer approval and have
**not** been done — see "Publication gate" at the bottom.

## Repository & code

- [x] Public GitHub repository created and pushed (`main` branch)
- [x] Apache-2.0 license adopted
- [x] Pre-publish security gate passed (tests, compileall, sanitization
      scan, gitleaks, bandit, pip-audit)
- [x] Fresh clone acceptance passed against the real GitHub repo
- [x] GitHub topics set

## Positioning & docs

- [x] README repositioned around material-change detection as the
      primary differentiator
- [x] Material update worked example (synthetic)
- [x] Pipeline comparison diagram (RSS reader / AI digest / this project)
- [x] Comparison table (`docs/COMPARISON.md`)
- [x] Competitor landscape (`docs/COMPETITOR_LANDSCAPE.md`) — named
      tools checked against their own public documentation; one
      suggested comparison (a tool called "FeedMind") was **dropped**
      because it could not be found/verified — see
      `docs/PUBLIC_RELEASE_ACCEPTANCE.md` for that note
- [x] Sample outputs (`examples/output/`: digest, collector health,
      material update)
- [x] Architecture/material-update/pipeline diagrams as Mermaid
- [x] Security-by-design section in README
- [x] Testing section in README (real, current test count)
- [x] ROADMAP.md (no pricing/commercial-edition language)
- [x] CONTRIBUTING.md expanded + issue templates

## Content pack (drafted, not published)

- [x] `docs/DEMO.md` — demo video script
- [x] `docs/launch/WHY_I_BUILT_THIS.md`
- [x] `docs/launch/LINKEDIN_EN.md` / `LINKEDIN_TR.md`
- [x] `docs/launch/SHORT_POST_EN.md` / `SHORT_POST_TR.md`
- [x] `docs/launch/YOUTUBE.md`

## Manual steps (cannot be done from this environment)

- [ ] GitHub social preview image upload (web UI only — see
      `docs/assets/README.md`)
- [ ] Recording and uploading the actual demo video
- [ ] Actually posting any of the drafted social content

## Publication gate

The following are **deliberately not done** pending explicit
maintainer approval, per this launch's own instructions:

- [ ] GitHub Release published / `v1.0.0-rc1` tag pushed
- [ ] LinkedIn post published
- [ ] YouTube video uploaded
- [ ] Any social post published

**Status: SOCIAL/RELEASE PUBLICATION — AWAITING USER APPROVAL.**

Progress: **17/19** checklist items complete (the 2 open items are the
manual-only steps above; the 4 publication-gate items are intentionally
held, not counted as blockers).
