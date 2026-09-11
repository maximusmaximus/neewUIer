#!/usr/bin/env bash
# Local quality gate — same checks GitHub Actions runs before merge.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HUB=""
if [[ -f hub/cinenode-hub.py ]]; then
  HUB=hub/cinenode-hub.py
elif [[ -f public/cinenode-hub.py ]]; then
  HUB=public/cinenode-hub.py
else
  echo "cinenode-hub.py not found" >&2
  exit 1
fi

echo "==> python self-test ($HUB)"
python3 "$HUB" --self-test

echo "==> pytest"
python3 -m pip install -q pytest
HUB_PATH="$HUB" python3 -m pytest hub/tests -q --tb=short

if [[ -f package.json ]]; then
  echo "==> node tests"
  if [[ -d node_modules ]]; then
    if npm run | grep -q "test:protocol"; then
      npm run test:protocol
    else
      npm test
    fi
    if npm run | grep -q "typecheck"; then
      echo "==> typecheck"
      npm run typecheck
    fi
  else
    node --experimental-strip-types --test src/lib/hub/*.test.ts
  fi
fi

echo "ok  all checks passed"
