#!/bin/sh
# Real-browser check: see run.py. From the repo root, after `npm run build`:
#   bash tools/browser_check/run.sh [script]
exec python3 "$(dirname "$0")/run.py" "$@"
