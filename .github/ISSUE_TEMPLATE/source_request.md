---
name: Source request
about: Request a new news or academic source
title: "[Source] "
labels: source-request
---

**Source name and URL**

**Kind**
- [ ] News (RSS/Atom feed)
- [ ] Academic (API-based collector)

**Why this source**
(What does it cover that existing sources in `docs/SOURCES.md` don't?)

**For a news/RSS source**: does the feed URL work when fetched directly
(`curl <url>`)? If so, this may not need a code change at all — see
"Adding a source" in [CONTRIBUTING.md](../../CONTRIBUTING.md).

**For an academic API source**: is there a free, documented, publicly
accessible API? Link the docs. A new API-based collector is a larger
change than a feed URL — see `cyber_radar/collectors/` for the shape
existing collectors follow.
