"""Public export acceptance gate: this repository must never contain
secrets, private identifiers, or infra-specific data. See
tools/sanitization_scan.py for the actual scanner and
docs/SANITIZATION_REPORT.md for what was checked and how. This test
fails the whole suite (and therefore CI) if the scanner finds anything -
the sanitization gate is not optional or advisory."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from sanitization_scan import find_all_issues  # noqa: E402


def test_no_secrets_or_private_identifiers_in_public_tree():
    issues = find_all_issues()
    assert issues == [], "Sanitization scan found issues:\n" + "\n".join(issues)


def test_scanner_actually_detects_injected_private_marker(tmp_path):
    """Proves the scanner isn't a no-op: a file containing a denylisted
    identifier must be flagged."""
    bad_file = tmp_path / "leaked.py"
    bad_file.write_text("# accidentally left in: v4gus was here\n")
    issues = find_all_issues(root=str(tmp_path))
    assert any("v4gus" in i for i in issues)


def test_scanner_detects_injected_secret_pattern(tmp_path):
    """Assembled from fragments at runtime (not one contiguous literal) so
    this test file's own git blob never contains a string that itself
    matches a real secret-scanner pattern (gitleaks/GitHub push
    protection) - the injected value below is fake and never a live key
    either way, but a contiguous literal would still trip external
    scanners on this file at rest."""
    fake_key = "AIza" + "SyDaGmWKa4JsXZ" + "-HjGw7ISLn_3namBGewQe"
    bad_file = tmp_path / "leaked_key.py"
    bad_file.write_text(f'GEMINI_API_KEY = "{fake_key}"\n')
    issues = find_all_issues(root=str(tmp_path))
    assert any("Google API key" in i for i in issues)


_PRIVATE_PKG_NAME = "".join(["s", "r", "c"])  # spelled out so sed/find-replace passes over this repo can't touch it
_PRIVATE_IMPORT_PREFIXES = (f"from {_PRIVATE_PKG_NAME}.", f"from {_PRIVATE_PKG_NAME} import", f"import {_PRIVATE_PKG_NAME}")


def test_no_imports_from_private_src_tree():
    """The public export must be self-contained - no import referencing
    the PRIVATE repository's package name (built as a runtime string so
    this very check doesn't get rewritten by a future find-and-replace
    the way it once accidentally was during the export process)."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    offenders = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", "__pycache__", "data")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(_PRIVATE_IMPORT_PREFIXES):
                        offenders.append(f"{os.path.relpath(path, repo_root)}: {stripped}")
    assert offenders == [], "Found imports referencing the private 'src' package:\n" + "\n".join(offenders)
