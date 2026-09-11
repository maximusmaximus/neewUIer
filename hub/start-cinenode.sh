#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "Python 3 is required (python.org, Homebrew, or your package manager)."
  exit 1
fi

echo "Installing bleak + paho-mqtt..."
"$PYTHON" -m pip install --user --upgrade bleak paho-mqtt

if [[ ! -f cinenode.json && -f cinenode.example.json ]]; then
  cp cinenode.example.json cinenode.json
  echo "Wrote cinenode.json from the example — edit MQTT broker if needed."
fi

echo "Starting CineNode hub. Close the official Neewer app first."
echo "Home Assistant color commands: topic cinenode/<light-id>/set"
exec "$PYTHON" cinenode-hub.py "$@"
