# Launch Checklist

Tracks readiness for the visibility-first public launch.
**v1.0.0-rc1 is LIVE** — https://github.com/4rslanismet/cyber-intelligence-radar/releases/tag/v1.0.0-rc1

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
- [x] `docs/launch/RELEASE_NOTES_v1.0.0-rc1.md` — used as the published
      release body (root-relative links corrected for the Release page)
- [x] `docs/launch/LINKEDIN_EN.md` / `LINKEDIN_TR.md` — finalized with
      the live release URL as primary CTA

## Manual steps (cannot be done from this environment)

- [x] GitHub social preview **asset created**
      (`docs/assets/github-social-preview.png`, 1280×640)
- [x] GitHub social preview **uploaded** (done by the maintainer via
      Settings → General → Social preview)
- [ ] Recording and uploading the actual demo video (explicitly NOT a
      release blocker — see `docs/DEMO.md` / `docs/launch/YOUTUBE.md`)
- [ ] Actually posting the LinkedIn copy (maintainer posts manually —
      no auto-posting)

## Publication gate

- [x] GitHub Release published / `v1.0.0-rc1` tag pushed — **LIVE**
- [ ] LinkedIn post published (copy is final and ready; posting is a
      manual maintainer action)
- [ ] YouTube video uploaded (not a blocker; recorded later)
- [ ] Short social posts published (drafts ready in
      `docs/launch/SHORT_POST_EN.md` / `SHORT_POST_TR.md`)

**Status: RELEASE — LIVE. Remaining social publication — maintainer's
own action, whenever they choose.**

## Post-release phase

Per explicit instruction: no new feature development starts right after
`v1.0.0-rc1`. Next phase is observation only — GitHub traffic, stars,
issues, clone/setup feedback, bug reports, feature requests — with new
feature work evaluated only against real feedback, not spec-driven.

Progress: **19/19** checklist items where "done" was ever required for
release; the remaining 2 open boxes (video recording, actual social
posting) are the maintainer's own future actions, not blockers.
