# Roadmap

Directional, not a commitment or a schedule. This is an open-source
project maintained around other work — items move based on real
usage/feedback and available time, not a fixed release calendar.

## Under consideration

- **More source connectors** — additional news/academic sources beyond
  what ships today (see `docs/SOURCES.md` for the current set and how
  to add one yourself in the meantime).
- **Profile sharing** — a way to publish and pull community-contributed
  research profiles (see `profiles/examples/`) without hand-copying
  YAML files.
- **Richer research workflows** — extending the two-slot "Research
  Profile A/B" digest-bridge mechanism (see `docs/PROFILES.md`) toward
  more flexible, possibly N-profile support.
- **UI/dashboard** — a local web view of the digest and collector health
  report, as an alternative to Markdown/Telegram.
- **Visualization** — rendering the citation-relationship graph
  (BUILDS_ON/FOUNDATION_FOR) rather than only exposing it as structured
  data.
- **MISP/OpenCTI integrations** — optional export of structured
  findings toward existing TIPs, for users who already run one (see
  `docs/COMPETITOR_LANDSCAPE.md` for how this project relates to those
  platforms).
- **Community profiles** — a curated, reviewed set of contributed
  profiles beyond the four examples shipped today.
- **Local LLM support** — an alternative to the Gemini API for users who
  want the analysis step to stay fully local (see `docs/PRIVACY.md` for
  why this matters and the current constraint).

## Not planned

Nothing here is being built toward a paid tier, pricing model, or
commercial/enterprise edition. This is a personal open-source project;
see [CONTRIBUTING.md](CONTRIBUTING.md) if you'd like to help with any of
the above, and open an issue if you'd like to propose something not on
this list.
