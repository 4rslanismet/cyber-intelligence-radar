# Demo Video Script (2-3 minutes)

Not recorded yet — this is the script/outline for whoever records it
(the maintainer or a contributor). Screen-recording a real terminal
session running the commands below is the intended format.

## 0:00-0:20 — Hook

> "Every day I was reading the same 30 security headlines and academic
> papers, re-checking things I'd already seen yesterday to see if
> anything actually changed. So I built something that asks a different
> question: not 'is this new?' but 'what actually changed?'"

Show the README hero line on screen: **"It does not just ask 'Is this
new?' — it asks 'What actually changed?'"**

## 0:20-0:50 — Material update example

Walk through `examples/output/sample_material_update.md` on screen: the
07:30 first-seen state, then the 19:30 re-check with KEV/exploitation/IOC
changes, then "RESURFACED — Reason: MATERIAL UPDATE."

> "This is entirely synthetic, documentation-only data — but it's
> exactly the shape of comparison the tool runs on every real event."

## 0:50-1:30 — Live terminal: install to demo

Run on screen, real terminal, real output:

```bash
git clone https://github.com/4rslanismet/cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cyber-radar setup --non-interactive
cyber-radar doctor
cyber-radar demo
```

Narrate while it runs:

> "No API keys, no network calls, no database needed for this part —
> demo mode uses fixture data to show you the exact digest format."

## 1:30-2:00 — Digest walkthrough

Scroll through the demo digest output on screen, pointing out: the four
operational categories (Action Required / Hunt Opportunity / Technical
Learning / Awareness), the academic reading list sections (Current,
Foundation→Current, Classic, Historical), and one Research Profile
section.

## 2:00-2:30 — Architecture in one breath

Show `docs/assets/architecture.mmd` rendered (or the ARCHITECTURE.md
page on GitHub, which renders it inline):

> "Under the hood: collect, normalize, deduplicate, merge into events,
> check for material change, enrich with an LLM, verify every claim
> against the source text, prioritize, and brief — locally or via
> Telegram, with an optional Drive archive."

## 2:30-2:50 — Close

> "It's self-hosted, Apache-2.0, and the whole pipeline — including the
> academic side — is one `pip install -e .` away. Link's in the
> description. I'd genuinely like feedback, especially on the
> material-update logic — that's the part I'm proudest of."

Show: GitHub URL, topics, and the license badge.

## Notes for whoever records this

- Use a real terminal with a readable font size (14pt+) and high
  contrast theme — this will be watched at 720p-1080p on mobile a lot.
- Don't use a real Gemini API key on screen; the fake-key path used
  throughout this project's own acceptance testing (`GEMINI_API_KEY=
  fresh-env-check-fake-key` style) is fine for a demo recording too,
  since `cyber-radar demo` doesn't call it anyway.
- Trim dead air from `pip install` — nobody needs to watch progress
  bars for two minutes.
