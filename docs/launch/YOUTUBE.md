# YouTube Upload Pack — Draft

*Not uploaded. Metadata pack to go with the recording described in
[docs/DEMO.md](../DEMO.md).*

## Title options

- Cyber Intelligence Radar: it doesn't ask "is this new?" — it asks "what changed?"
- I built a self-hosted threat intel radar that tracks material changes, not just headlines
- Cyber Intelligence Radar — demo & architecture walkthrough

## Description draft

```
Cyber Intelligence Radar is a self-hosted pipeline that collects
cybersecurity news and academic papers, deduplicates events across
sources, and — the part I actually built this for — only re-surfaces
an event when something material changes about it (a KEV listing, a
new IOC, confirmed active exploitation, a fix shipping), instead of
repeating the same headline every time a source re-publishes it.

It does the same profile-driven relevance scoring for academic papers,
and every structured claim it makes (CVE IDs, IOCs, CWE mappings) is
mechanically checked against the source text before it reaches the
digest.

00:00 Why I built this
00:20 Material update example
00:50 Install → demo, live
01:30 Digest walkthrough
02:00 Architecture in one breath
02:30 Wrap-up

Repo (Apache-2.0): https://github.com/4rslanismet/cyber-intelligence-radar
Docs: see the repo's docs/ directory
Comparison to adjacent tools: docs/COMPARISON.md, docs/COMPETITOR_LANDSCAPE.md

This is a technical demo, not a sales pitch — feedback and issues are
welcome on GitHub.
```

## Tags

cybersecurity, threat intelligence, open source, python, self-hosted,
security automation, CVE, CISA KEV, academic research, LLM

## Thumbnail idea

Split-screen: left = the 07:30 "Unknown/No/None" state, right = the
19:30 "YES/YES/new IOC" state, center arrow labeled "MATERIAL UPDATE" —
built from `examples/output/sample_material_update.md`'s content.
