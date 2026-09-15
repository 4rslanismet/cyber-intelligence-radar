# Visual Assets

Diagram sources for this project, kept as Mermaid (`.mmd`) rather than
rasterized images: they render natively in GitHub's Markdown viewer,
stay diffable in version control, and don't need an external design
tool to update. Each one is also embedded directly in the relevant doc
inside a ` ```mermaid ` fence.

| File | Used in | Shows |
|---|---|---|
| `architecture.mmd` | [ARCHITECTURE.md](../ARCHITECTURE.md) | Full collection→brief pipeline |
| `material_update_flow.mmd` | [README.md](../../README.md), [COMPARISON.md](../COMPARISON.md) | The CVE-2026-DEMO material-update example |
| `pipeline_comparison.mmd` | [README.md](../../README.md) | RSS reader vs. AI digest bot vs. this project |

## GitHub social preview

`github-social-preview.png` (1280×640, rendered from `github-social-preview.svg`
via `rsvg-convert`) — title, tagline, and a minimal six-stage pipeline
motif (Sources → Normalize → Deduplicate → Material Change → Relevance →
Brief) on a dark, technical background. No personal data, hostnames,
IPs, tokens, or paths. Uploading it is still a manual step (see below) —
GitHub has no API for this.

## "Setup example" and "doctor example" assets

These are represented as real terminal output (copy-pasteable code
blocks), not screenshots — see the Quickstart section of
[README.md](../../README.md) and section 37 of
[PUBLIC_RELEASE_ACCEPTANCE.md](../PUBLIC_RELEASE_ACCEPTANCE.md) for the
actual `cyber-radar doctor` output captured during acceptance testing.
A real terminal-recording GIF/screenshot would be a nice future addition
but isn't included here — see the note below.

## What's NOT included here (and why)

No rasterized (PNG/SVG/JPG) images are checked into this repository yet
— every diagram above renders as Mermaid instead, and no terminal
recording (asciinema/GIF) has been produced. Two things called for in
the visibility-launch scope specifically require a human with access to
the GitHub web UI and cannot be done from this environment:

- **GitHub social preview image** (Settings → General → Social preview,
  on the repository's GitHub page) — GitHub does not expose an API for
  uploading this image; it's a web-UI-only upload.
  **MANUAL STEP REQUIRED.** The asset itself is ready:
  `github-social-preview.png` (see above) — upload that file at
  Settings → General → Social preview.
- **A rendered PNG/SVG export of the Mermaid diagrams**, for contexts
  that don't render Mermaid (some external link previews, non-GitHub
  viewers). Optional — the diagrams already render correctly on GitHub
  itself, which covers the primary use case.
