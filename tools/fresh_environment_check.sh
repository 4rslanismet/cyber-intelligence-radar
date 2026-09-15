#!/usr/bin/env bash
# Fresh-environment acceptance check (see docs/PUBLIC_RELEASE_ACCEPTANCE.md
# section 34). Copies the git-tracked tree into an isolated temp directory,
# installs into a brand-new venv, and verifies setup/doctor/demo/db-init/
# tests all work with ZERO dependency on this machine's private repo,
# private .env, private database, or existing systemd state.
#
# Usage: bash tools/fresh_environment_check.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d)"
echo "Fresh environment: $WORKDIR"
trap 'echo "Cleaning up $WORKDIR"; rm -rf "$WORKDIR"' EXIT

cd "$REPO_ROOT"
git archive HEAD | (mkdir -p "$WORKDIR/repo" && cd "$WORKDIR/repo" && tar -x)
cd "$WORKDIR/repo"

echo "--- No private paths/imports in the copied tree ---"
if grep -rn "/home/v4gus\|/home/[a-z]*/cyber-radar" . --include="*.py" --include="*.md" --include="*.example" 2>/dev/null; then
  echo "FAIL: found a private path reference"; exit 1
fi

echo "--- Fresh venv ---"
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"

echo "--- setup --non-interactive ---"
cyber-radar setup --non-interactive

echo "--- Point at an isolated test database (not the developer machine's real DB) ---"
sed -i.bak "s#^DATABASE_URL=.*#DATABASE_URL=${FRESH_ENV_DB_URL:-postgresql://cyber_radar_public:public_test_pw@localhost:5432/cyber_radar_fresh_env_check}#" .env
sed -i.bak "s#^GEMINI_API_KEY=.*#GEMINI_API_KEY=fresh-env-check-fake-key#" .env

echo "--- db init ---"
cyber-radar db init

echo "--- doctor ---"
cyber-radar doctor || true  # LLM/Telegram checks are expected to warn/fail with a fake key - not the point of this check

echo "--- demo (zero live calls) ---"
cyber-radar demo > /dev/null

echo "--- profiles list/validate ---"
cyber-radar profiles list
cyber-radar profiles validate

echo "--- test suite (against the isolated DB) ---"
TEST_DATABASE_URL="${FRESH_ENV_DB_URL:-postgresql://cyber_radar_public:public_test_pw@localhost:5432/cyber_radar_fresh_env_check}" pytest -q

echo "--- sanitization scan (on the FRESH COPY, not the dev tree) ---"
python tools/sanitization_scan.py

echo
echo "FRESH ENVIRONMENT CHECK: PASS"
