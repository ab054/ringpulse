#!/usr/bin/env bash
# Commit health.json to the `ci-health` branch (created empty on first use). Run from the repository root, last:
# it replaces the working tree with that branch's.
set -euo pipefail
FILE=${1:-health.json}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
SAVED=$(mktemp)
cp "$FILE" "$SAVED"

if git ls-remote --exit-code --heads origin ci-health > /dev/null; then
  git fetch --depth=1 origin ci-health
  git checkout -q -f -B ci-health FETCH_HEAD
else
  git checkout -q -f --orphan ci-health
  git rm -rfq . || true
fi

cp "$SAVED" health.json
git add health.json
if git diff --cached --quiet; then
  echo "health.json unchanged"
else
  git commit -qm "Update test health (run ${GITHUB_RUN_ID:-local})"
  git push -q origin ci-health
fi
