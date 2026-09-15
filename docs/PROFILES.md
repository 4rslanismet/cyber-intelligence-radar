# Research Profiles

A research profile is a YAML file describing what the radar should look
for — search terms, and optionally a scoring rubric for a dedicated
digest section. Profiles are loaded from `profiles/<id>.yaml`.

## The default profile

`profiles/daily_cyber.yaml` reproduces the plain `KEYWORDS`-driven
behavior: each keyword in your `.env` is queried independently, with no
extra scoring rubric. This is what runs out of the box.

## Example profiles

See `profiles/examples/`:

- `soc_analyst.yaml` — SOC alert triage / detection engineering focus,
  full digest-bridge example
- `cti_analyst.yaml` — threat intelligence focus, collection-only
  (no dedicated digest section)
- `dfir_analyst.yaml` — forensics/incident response focus, collection-only
- `security_researcher.yaml` — applied security research focus, with
  citation snowballing and a full digest-bridge example

To activate one, copy it into `profiles/` and add its `id` to
`ACTIVE_RESEARCH_PROFILES`:

```bash
cp profiles/examples/soc_analyst.yaml profiles/
```

```
ACTIVE_RESEARCH_PROFILES=daily_cyber,soc_analyst
```

## Writing your own profile

Minimum viable profile (collection-only, no dedicated digest section):

```yaml
id: my_profile
title: "My Custom Focus"
mode: research
concept_groups:
  my_topic:
    - some search phrase
    - another search phrase
queries:
  - [my_topic]
```

`queries` is a list of AND-groups; each group is a list of concept-group
names whose terms are OR'd together. `queries: [[a, b]]` means
`(a's terms OR'd) AND (b's terms OR'd)`.

## Research Profile A / B: a dedicated digest section

Any **two** of your active profiles can be assigned their own scored
digest section (see `README.md`'s example digest, and `cyber_radar/cli/demo.py`
for exactly what this looks like) by setting:

```
RESEARCH_PROFILE_A_ID=my_profile
```

For this to produce anything beyond "not yet analyzed", your profile
needs an `extraction_schema` with a `digest_bridge` object — see
`profiles/examples/soc_analyst.yaml` for a complete example. The
renderer is **fully generic**: whatever fields your schema's
`digest_bridge` defines are shown with their field name humanized as the
label. No code change is needed to add a new profile with new fields.

The renderer looks for three top-level fields by default (configurable
per slot via `RESEARCH_PROFILE_A_SCORE_FIELD`/`_REASON_FIELD`/`_DIMS_FIELD`,
see `.env.example`):

- `relevance_score` (0-10) — shown as "Relevance score"
- `why_relevant` (string) — shown as "Why relevant"
- `relevance_dimensions` (object of 0-10 scores) — dimensions scoring
  ≥6 are listed as "Strongest dimensions" (this is computed
  deterministically from your already-collected scores, no extra LLM
  call or extra fabrication risk)

Everything else lives under `digest_bridge` and is rendered verbatim.

## Snowball citation expansion

Setting `snowball: true` on a profile enables citation-graph expansion:
after collecting your seed papers, the radar also looks at what they
cite and what cites them (via OpenCitations, no key required),
respecting `snowball_seed_limit` to keep this bounded. See
`security_researcher.yaml` for an example.

## Validating your profiles

```bash
cyber-radar profiles list       # shows every profile found, and which are active
cyber-radar profiles validate   # validates the currently active ones
```
