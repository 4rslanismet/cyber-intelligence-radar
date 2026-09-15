# LinkedIn Post (EN) — Draft

*Draft only — not published. Review/edit before posting; this is written
in first person for the maintainer.*

---

Every day I was tracking dozens of security news sources and academic
papers, and kept running into the same problem: most of what I was
re-reading wasn't new — it was the same event, reported again, or
already in my digest from yesterday.

So I built Cyber Intelligence Radar around a different question. Not
"is this new?" — but **"what actually changed?"**

It tracks the same underlying event (a CVE, an incident) across
multiple runs, and only re-surfaces it when something material happens:
a KEV listing, a confirmed active-exploitation status, a new IOC, a
fix shipping. A source re-publishing the same content doesn't trigger a
repeat — an actual change does.

It also does the same for academic papers: a small, curated reading
list built from profile-driven relevance scoring, not a search engine.
And every structured claim it makes (CVE IDs, IOCs, CWE mappings) is
mechanically checked against the original source text before it reaches
the digest — evidence-first, not "trust the model."

It's self-hosted, open source (Apache-2.0), and the whole pipeline is
one `pip install -e .` + `cyber-radar demo` away — no API keys or
network calls needed to see a full sample digest.

Repo: https://github.com/4rslanismet/cyber-intelligence-radar

I'd genuinely like feedback — especially on the material-update
detection logic, which is the part of this I'm proudest of.

#cybersecurity #threatintelligence #opensource #python #selfhosted
