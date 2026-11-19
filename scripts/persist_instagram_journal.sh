#!/usr/bin/env bash
set -euo pipefail

journal="historique/instagram"
if [ -z "$(git status --porcelain -- "$journal")" ]; then
    exit 0
fi

git config user.name "dco-agent-editorial"
git config user.email "actions@github.com"
git add -- "$journal"
git commit -m "Journal de publication Instagram Rachel [skip ci]"

for attempt in 1 2 3; do
    git pull --rebase origin main
    if git push origin HEAD:refs/heads/main; then
        exit 0
    fi
    sleep "$attempt"
done
exit 1
