# Why I Built This

*Draft for a personal/technical blog post or long-form LinkedIn article.
Written in first person for the maintainer to publish under their own
name — review and adjust before publishing anywhere.*

## 1. Information overload

Every day: dozens of security news sources, several academic feeds,
and a Telegram habit of scrolling through the same three or four
"what's new in security" accounts. Most of it wasn't new information —
it was the same handful of real events, reported by five different
outlets, arriving at five different times.

## 2. Duplicate news

The first thing I actually needed wasn't summarization — it was
deduplication that understood *events*, not articles. Ten articles about
the same CVE are one event. A basic dedup on title/URL doesn't get you
there; you need to normalize what the article is actually reporting on
(CVEs mentioned, IOCs, the vendor/product) and merge on that.

## 3. Why summarization was not enough

Once dedup worked, the next problem showed up immediately: even a
correctly-deduplicated event isn't static. A CVE reported at 07:30 with
"no known exploitation" can be actively exploited with a public IOC by
19:30. A tool that only summarizes each *article* has no way to notice
that — it just re-summarizes the same event with slightly different
words. What I actually wanted to know was: **did anything change that
I'd act on differently?**

## 4. Material update detection

That question became the core mechanism: track the same event across
runs, and only re-surface it when a *material* field changes — KEV
listing, exploitation status, a new IOC, a newly available fix. See
[docs/COMPARISON.md](../COMPARISON.md#what-material-change-detection-means-here)
for the concrete example. Everything else in the pipeline exists to
support this one decision correctly.

## 5. Operational relevance

Not every reader needs the same digest. A researcher and a SOC analyst
reading the same CVE report want different things from it. So the
pipeline splits operational news into four categories (Action Required,
Hunt Opportunity, Technical Learning, Awareness) instead of one
undifferentiated feed, and scores relevance per-reader rather than
globally.

## 6. Evidence-first design

LLMs fabricate. A CVE ID or IOC that the model claims but that doesn't
literally appear in the source text is worse than useless in a security
tool — it's actively misleading. So every structured claim gets
mechanically checked against the source text after generation, and
dropped if it doesn't check out. This is a second, independent guard on
top of prompt instructions, not a replacement for them.

## 7. Academic intelligence

The same "what changed / what's actually relevant" problem exists for
research papers, just on a slower clock. I wanted a small, curated
reading list — not a search engine, not a citation-network explorer —
built from the same profile-driven relevance logic as the news side,
plus a sense of how a new paper relates to what came before it
(BUILDS_ON/FOUNDATION_FOR).

## 8. Recovery/resilience

A pipeline that silently breaks and stops sending digests is worse than
one that's a little noisy. Collector-level health tracking, per-source
anomaly detection (a source going quiet for several runs in a row gets
flagged, not just logged), and a cross-process-safe rate limiter for the
external academic APIs all exist because a one-person operation has no
on-call rotation to catch a quiet failure.

## 9. Architecture

Collect → Normalize → Deduplicate → Merge Event → Detect Material Change
→ Enrich → Evaluate Relevance → Verify Evidence → Prioritize → Brief →
Archive → Recover → Feed Research Workflows. See
[ARCHITECTURE.md](../ARCHITECTURE.md) for the full breakdown, including
budget isolation between news and academic LLM usage so one never
starves the other.

## 10. What I learned

Deduplication is the hard problem, not summarization — most of the
interesting engineering work here is in deciding what counts as "the
same thing" and "a real change," not in prompting an LLM well. Also:
building the sanitization/export tooling to turn a year of
private-deployment-specific code into something safe to publish was
almost its own project — see
[docs/PUBLIC_RELEASE_ACCEPTANCE.md](../PUBLIC_RELEASE_ACCEPTANCE.md) if
you're curious what that process looked like end to end.

## 11. What's next

See [ROADMAP.md](../../ROADMAP.md). Short version: more source
connectors, profile sharing, and eventually a UI — but the core
monitoring/material-change/briefing loop is the part I wanted to get
right before anything else.
