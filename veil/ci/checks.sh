#!/bin/bash
# Veil's fast checks: no compiling, ~10 min. CI runs this on every push; it
# runs the same on a Mac or in `docker run ubuntu`.
#   1. every Veil script parses, every JSON file is valid
#   2. the Firefox source downloads and its signature verifies (make fetch)
#   3. LibreWolf's patches and Veil's layer apply (make dir)
#   4. every pref and policy Veil sets exists in this Firefox; the updater
#      is on, with Veil's keys and address (check_tree.py)
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -m py_compile veil/*.py veil/tools/*.py veil/tests/*.py
for f in veil/tools/*.sh veil/ci/*.sh; do bash -n "$f"; done
for f in veil/*.json; do python3 -m json.tool "$f" > /dev/null; done
echo "scripts and JSON OK"
make fetch
make dir > dir.log 2>&1 || { tail -40 dir.log; exit 1; }
git checkout -q -- assets/mozconfig.new 2>/dev/null || true
python3 veil/tools/check_tree.py "librewolf-$(cat version)-$(cat release)"
