# Competitor & Adjacent-Tool Landscape

Cyber Intelligence Radar is **not** a Threat Intelligence Platform (TIP)
and does not try to be one. This document places it next to some
well-known adjacent tools so a visitor can quickly tell whether it's
the right tool for their use case, without any "first/only/best/unique"
claims — none of those are verifiable, so none are made.

Positioning summaries below reflect each project's own public
documentation as of this writing; verify against the project's current
docs before relying on specifics, since these tools evolve.

## Threat Intelligence Platforms (structured IOC/knowledge-graph tools)

**[MISP](https://www.misp-project.org/)** is an open-source platform for
storing, correlating, and sharing structured threat intelligence
(IOCs, events, galaxies) between organizations and communities. Its core
strength is structured sharing and correlation at the indicator level.
Cyber Intelligence Radar does not store or share IOCs as a community
graph — it produces a readable daily briefing for one person/team from
news and academic sources.

**[OpenCTI](https://github.com/OpenCTI-Platform/opencti)** is an
open-source cyber threat intelligence platform (Filigran) built around a
STIX2 knowledge graph, with a large connector ecosystem for ingesting
and linking intelligence from many sources into that graph. It's an
analyst workbench for organizing and relating intelligence over time.
Cyber Intelligence Radar has no knowledge-graph/entity-relationship
model — it's a monitoring-and-briefing tool, not an intelligence
warehouse.

**[IntelOwl](https://github.com/intelowlproject/IntelOwl)** is an
open-source observable/indicator analysis tool: you submit an IP, hash,
domain, or URL, and it queries a large set of analyzer integrations
(sandboxes, reputation services, etc.) and aggregates the results.
It's on-demand lookup/enrichment for a specific observable, not a
scheduled news/research monitoring pipeline.

## Commercial AI-assisted feed tools

**[Feedly Threat Intelligence](https://feedly.com/threat-intelligence)**
is a commercial, cloud-hosted product that uses AI to track threat
actors, vulnerabilities, and TTPs across a large curated set of web
sources and generates summarized intelligence. Cyber Intelligence Radar
is self-hosted (your data stays on infrastructure you control except for
the LLM calls you explicitly configure) and open source, rather than a
multi-tenant SaaS product.

**[CassandraCTI](https://github.com/franckferman/CassandraCTI)** is an
open-source, self-hostable pipeline that collects threat intel from RSS
feeds, ransomware trackers, and threat feeds (CISA KEV, abuse.ch),
deduplicates items, and distributes them to chat platforms (Teams,
Discord, Telegram, Signal) and a live dashboard, with optional
AI-generated briefs. It's the closest tool on this list to Cyber
Intelligence Radar's "collect → dedup → distribute" shape. The main
differences, based on its public documentation: CassandraCTI's dedup is
fingerprint-based (send each item once); Cyber Intelligence Radar goes a
step further by tracking the *same underlying event* across multiple
reports over time and re-surfacing it only when something material
changes about it (see [COMPARISON.md](COMPARISON.md)), and pairs
operational cyber news with an independent academic-paper intelligence
track (reading paths, profile-based relevance scoring) that isn't part
of CassandraCTI's scope.

## Academic literature discovery

**[Semantic Scholar](https://www.semanticscholar.org/)** is a large,
free, AI-powered academic search engine with citation graphs and
AI-generated paper summaries ("TL;DRs"). It's a general-purpose
discovery/search tool, not a personalized, profile-driven, recurring
monitoring workflow. Cyber Intelligence Radar's academic collectors
query several of the same underlying open academic APIs (including
sources that themselves build on Semantic Scholar's data) but frame the
output as a small, recurring, curated reading list rather than a search
interface.

**[ResearchRabbit](https://www.researchrabbit.ai/)** helps researchers
explore citation networks interactively starting from one or more seed
papers ("Spotify for papers") — a discovery/visualization tool for
exploring a literature landscape. Cyber Intelligence Radar's citation
relationship tracking (BUILDS_ON/FOUNDATION_FOR) serves a narrower,
adjacent purpose: placing a *newly collected* paper in context of what
it builds on, inside an automated daily pipeline, not an interactive
exploration session.

## Where Cyber Intelligence Radar fits

Its primary focus is **monitoring, prioritization, material-change
detection, personalized briefing, and academic intelligence for a
single person or small team** — not organization-wide IOC sharing, not
a knowledge-graph analyst workbench, not on-demand observable lookup,
and not interactive literature exploration. See
[COMPARISON.md](COMPARISON.md) for a capability-level comparison table.

If your need is IOC sharing across organizations, look at MISP or
OpenCTI. If your need is looking up a specific observable across many
sources, look at IntelOwl. If your need is exploring a citation network
interactively, look at ResearchRabbit. If your need is "give me one
readable briefing a day, and only re-surface something I've already
seen when it actually changed" — that's what this project is for.
