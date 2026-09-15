# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately rather than opening a
public issue. Use this repository's private vulnerability reporting
feature (if available on the hosting platform) or contact the
maintainer directly through the contact method listed on their profile.

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (a minimal example if possible)
- Any suggested fix, if you have one

We aim to acknowledge reports within a reasonable timeframe and will
credit reporters (unless you prefer to stay anonymous) once a fix is
released.

## Scope

This is a self-hosted, single-operator tool with no network-listening
service by default (see `docs/SECURITY.md` "Network exposure"). The
most relevant vulnerability classes are:

- Secret/credential leakage
- SSRF via configured feed URLs or PDF resolution
- Injection via LLM-processed external content (prompt injection)
- Unsafe deserialization/parsing of external data (RSS/XML, PDF)

See `docs/SECURITY.md` for the technical detail on how each of these is
currently mitigated, and `docs/KNOWN_LIMITATIONS.md` for known,
disclosed gaps that are not yet fixed (not vulnerabilities requiring a
private report — already tracked openly).

## Supported versions

This project is at `0.1.0` (public preview) — there is currently only
one supported line. This section will be updated once a versioning
policy with multiple maintained branches exists.
