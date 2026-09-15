# Capability Comparison

A category-level comparison of primary workflow focus, not a feature
checklist or a superiority claim. See
[COMPETITOR_LANDSCAPE.md](COMPETITOR_LANDSCAPE.md) for the named tools
and sourcing behind this table.

| Capability | RSS Reader | AI Digest Bot | TIP/CTI Platform (MISP/OpenCTI) | Academic Discovery (Semantic Scholar/ResearchRabbit) | Cyber Intelligence Radar |
|---|---:|---:|---:|---:|---:|
| News collection | ✅ | ✅ | ✅ | ❌ | ✅ |
| Academic discovery | ❌ | ❌ | Limited | ✅ | ✅ |
| Event deduplication | Limited | Limited | ✅ | N/A | ✅ |
| Material-change detection | ❌ | Usually ❌ | Varies | ❌ | ✅ |
| Personalized relevance | Basic | AI-dependent | Organization-focused | Research-focused | ✅ |
| Evidence-aware cyber output | ❌ | Usually ❌ | Varies | ❌ | ✅ |
| Recovery/backfill | Limited | Limited | Connector-dependent | N/A | ✅ |
| Self-hosted | Varies | Varies | Often | Usually no | ✅ |

This comparison describes primary workflow focus rather than claiming
complete feature parity or superiority. Capabilities vary by product and
deployment, and this table reflects each category's *typical* public
positioning, not an audit of every product in it — check a specific
tool's own documentation before choosing between them.

## What "Material-change detection" means here

Most feed/digest tools answer one question: **"Is this new?"** Cyber
Intelligence Radar also asks: **"What actually changed?"** — see the
worked example in the [README](../README.md#material-update-example).
An item already shown to you is only re-surfaced when something material
happens to it (e.g. a CVE gets a KEV listing, a new IOC appears, a fix
ships), not on every re-crawl of the same source.

## What "Evidence-aware" means here

Structured claims (CVE IDs, IOCs, CWE mappings) extracted by the LLM are
mechanically checked against the original source text after generation
— a claim that doesn't literally appear in the source is dropped before
it reaches the digest or the database. See
[ARCHITECTURE.md](ARCHITECTURE.md#provenance-and-hallucination-guards).
