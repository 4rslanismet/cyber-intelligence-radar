#!/usr/bin/env python3
"""Public sanitization scanner (see docs/SANITIZATION_REPORT.md).

Scans every tracked, text-readable file in this repository for classes of
private/secret data that must never appear in a public export: API key
patterns, tokens, passwords in URLs, private/internal IP addresses, a
denylist of known-private identifiers (this deployment's username,
hostname, org acronym, GitHub handle, and the private repo's own name),
and generic secret-looking high-entropy assignments.

Deliberately does NOT hardcode any real secret VALUE (API key, password,
token) anywhere in this file - only patterns and non-secret identifying
strings (a username, a hostname, an org acronym) used to catch accidental
copy-paste from the private deployment. Run standalone:

    python3 tools/sanitization_scan.py

or via pytest: tests/test_public_sanitization.py imports and asserts on
find_all_issues(). Exit code 0 = clean, 1 = issues found.
"""
from __future__ import annotations

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories/files never scanned (build artifacts, VCS metadata, this
# scanner's own docstring/patterns would otherwise flag itself; .env/.env.bak
# are gitignored runtime artifacts, not the published tree this gate checks).
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", "node_modules", "data", ".pytest_cache", "build", "dist"}
EXCLUDED_FILES = {
    os.path.join("tools", "sanitization_scan.py"),
    os.path.join("tools", "fresh_environment_check.sh"),
    os.path.join("tests", "test_public_sanitization.py"),
}
EXCLUDED_FILENAMES = {".env", ".env.bak"}  # matched by basename, wherever they appear

# Known-private, non-secret identifiers - if any of these literal strings
# appear anywhere in the public tree, it is near-certain evidence of an
# accidental copy from the private deployment (username, hostname, GitHub
# org/handle, internal project acronym). These are NOT secrets themselves
# (no password/key/token value is ever placed here) - they are canary
# strings for detecting leakage.
PRIVATE_IDENTIFIER_DENYLIST = [
    "v4gus",
    "aiozet",
    "SHGM",
    "cyber-radar-public",  # working name used only during this export process
]
# Note: the repository owner's GitHub handle is deliberately NOT on this
# denylist - it is the intended public copyright holder/owner of this
# repository (see LICENSE) and its presence there is expected, not a leak.

# Generic secret-shaped patterns - each is (label, compiled regex).
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Google OAuth client secret", re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("Generic OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

URL_CREDENTIAL_PATTERN = re.compile(r"://[^/\s:@]+:([^/\s@]{4,})@")
_SAFE_PASSWORD_MARKERS = ("change_me", "password", "your_password", "your-password", "test", "ci_", "demo", "example", "fake", "placeholder")


def _is_safe_placeholder_password(password: str) -> bool:
    lowered = password.lower()
    if lowered.startswith("<") and lowered.endswith(">"):
        return True
    return any(marker in lowered for marker in _SAFE_PASSWORD_MARKERS)

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SAFE_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255", "8.8.8.8", "1.1.1.1"}
# Extremely common textbook/documentation example IPs, and the well-known
# public cloud-metadata address (used in SSRF-guard blocklists as a
# documented constant, not a real host of ours) - excluded to avoid
# flagging every "e.g. 192.168.1.1" example or security-guard constant.
_COMMON_EXAMPLE_IPS = {
    "192.168.1.1", "192.168.0.1", "192.168.1.100", "192.168.001.001",
    "10.0.0.1", "10.0.0.0", "172.16.0.1", "169.254.169.254",
}


def _is_private_or_suspicious_ip(ip: str) -> bool:
    if ip in _SAFE_IPS or ip in _COMMON_EXAMPLE_IPS:
        return False
    parts = [int(p) for p in ip.split(".") if p.isdigit()]
    if len(parts) != 4 or any(p > 255 for p in parts):
        return False
    a, b = parts[0], parts[1]
    # RFC1918 private ranges + link-local - real infra IPs, not sample/doc IPs.
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    return False


def _iter_text_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if rel in EXCLUDED_FILES or name in EXCLUDED_FILENAMES:
                continue
            if name.endswith((".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".db", ".sqlite", ".bak")):
                continue
            yield full, rel


def find_all_issues(root: str | None = None) -> list[str]:
    root = root or REPO_ROOT
    issues: list[str] = []
    for full_path, rel_path in _iter_text_files(root):
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue

        for marker in PRIVATE_IDENTIFIER_DENYLIST:
            if marker.lower() in text.lower():
                issues.append(f"{rel_path}: contains denylisted private identifier '{marker}'")

        for label, pattern in SECRET_PATTERNS:
            m = pattern.search(text)
            if m:
                issues.append(f"{rel_path}: matches secret pattern '{label}' (not showing the match itself)")

        for m in URL_CREDENTIAL_PATTERN.finditer(text):
            password = m.group(1)
            if not _is_safe_placeholder_password(password):
                issues.append(f"{rel_path}: connection URL has a non-placeholder-looking password (not showing the match itself)")

        # tests/ deliberately exercises the SSRF guard with illustrative
        # private-IP examples (10.0.0.5, 192.168.1.1, ...) - real fixture
        # data, not a leaked infra address. Skip the IP heuristic there;
        # the denylist/secret-pattern checks above still run on tests/.
        if not rel_path.startswith("tests" + os.sep):
            for ip in IP_PATTERN.findall(text):
                if _is_private_or_suspicious_ip(ip):
                    issues.append(f"{rel_path}: contains a private/internal-looking IP address ({ip})")

    return issues


def main() -> int:
    issues = find_all_issues()
    if not issues:
        print("Sanitization scan: no issues found.")
        return 0
    print(f"Sanitization scan: {len(issues)} issue(s) found:")
    for issue in issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
