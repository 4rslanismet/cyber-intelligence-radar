<!--
Synthetic, illustrative example of material-change detection (see
docs/ARCHITECTURE.md and docs/COMPARISON.md). CVE-2026-DEMO, the IP
address, and all other identifiers below are fabricated for
documentation purposes - this is not a real vulnerability report and
should not be looked up or acted on.
-->

# Material Update Example

Cyber Intelligence Radar tracks the same underlying event across
multiple source reports over time. It does not re-surface an
already-shown item just because a source re-published it — only when
something **material** actually changed.

## First seen — 07:30 UTC

```
CVE-2026-DEMO
Severity:              MEDIUM
KEV listed:            No
Active exploitation:   Unknown
Known IOC:             None
Fixed version:         Not yet available
```

Shown once in the morning digest under "👀 Awareness" (informational,
no listed exploitation, no fix yet — nothing actionable today).

## Same event, re-checked on a later run — 19:30 UTC

```
CVE-2026-DEMO
Severity:              CRITICAL
KEV listed:            YES  ← changed
Active exploitation:   YES  ← changed
Known IOC:             203.0.113.42 (example, RFC 5737)  ← new
Fixed version:         1.2.4  ← new
```

## Result: RESURFACED

```
Reason: MATERIAL UPDATE
  - KEV status: No → Yes
  - Exploitation status: Unknown → Confirmed active
  - New IOC published
  - Fix now available
```

Moved to "🚨 Action Required" in the next digest, with a note that this
is an update to an item already shown earlier today — not a duplicate.

## What counts as "material"

A change is material when it affects what an analyst would *do* about
an item: a severity change, a KEV/exploitation status change, a new
IOC, a patched/fixed version becoming available, or a materially revised
technical detail. A source simply re-publishing the same content, or a
cosmetic wording change, is not material and does not cause a
re-surface. See `cyber_radar/dedup.py` and
`tests/test_material_update_comparator.py` for the actual comparator
logic this example illustrates.
