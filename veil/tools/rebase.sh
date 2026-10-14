#!/bin/bash
# Move Veil onto a new LibreWolf release, check it, build it, test it.
#
#   veil/tools/rebase.sh [upstream-ref]     default: origin/main (LibreWolf)
#   veil/tools/rebase.sh --no-build ...     stop after the checks
#
# Veil's changes are commits on top of LibreWolf that touch only veil/ and
# one Makefile line, so a rebase rarely conflicts. Steps, stopping at the
# first failure with what to do next:
#   1. fetch upstream, rebase the veil branch onto it
#   2. download + verify the new Firefox source, build the source tree
#      (LibreWolf's patches, then veil/apply.py)
#   3. check_tree.py: every Veil pref/policy still exists in this Firefox
#   4. pref_diff.py: which settings LibreWolf changed under us
#   5. ./mach build (~45 min), then every test suite (veil/tests/run_all.py)
set -euo pipefail
cd "$(dirname "$0")/../.."
build=1
[ "${1:-}" = "--no-build" ] && { build=0; shift; }
remote=${UPSTREAM_REMOTE:-origin}  # the LibreWolf repo (on GitHub CI: "upstream")
ref=${1:-$remote/main}
step() { printf '\n==== %s\n' "$*"; }
tree() { echo "librewolf-$(cat version)-$(cat release)"; }

# LibreWolf's patch script rewrites this file in place on every tree build.
git checkout -q -- assets/mozconfig.new 2>/dev/null || true
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Uncommitted changes; commit or stash them first:" >&2; git status --short >&2; exit 1
fi

old=$(tree)
[ -f "$old/lw/librewolf.cfg" ] && cp "$old/lw/librewolf.cfg" /tmp/veil-old-librewolf.cfg

step "1. rebase $(git rev-parse --abbrev-ref HEAD) onto $ref"
git fetch -q "$remote" --tags
before=$(git rev-parse HEAD)
if ! git rebase "$ref"; then
  cat >&2 <<EOF

REBASE CONFLICT. Files in conflict:
$(git diff --name-only --diff-filter=U)
Veil only edits veil/ and the 'python3 veil/apply.py' line in the Makefile,
so keep upstream's version of everything else, re-add that one line, then:
  git add <files> && git rebase --continue && veil/tools/rebase.sh HEAD
Or undo everything:  git rebase --abort
EOF
  exit 2
fi
echo "rebased: $(git log --oneline "$ref"..HEAD | wc -l | tr -d ' ') Veil commits on top of $(git log -1 --format='%h %s' "$ref")"
echo "undo with: git reset --hard $before"

new=$(tree)
step "2. source tree $new"
if [ "$new" != "$old" ] || [ ! -d "$new" ]; then
  make fetch
  make dir || { echo "Building the tree failed: usually a LibreWolf patch that does not apply yet. Wait for upstream to fix it, or see the patch error above." >&2; exit 3; }
else
  python3 veil/apply.py "$new"
fi
git checkout -q -- assets/mozconfig.new 2>/dev/null || true

step "3. does everything Veil sets still exist?"
python3 veil/tools/check_tree.py "$new" | grep -v '^ok ' || { echo "Fix the PROBLEM lines above (rename or drop the pref in veil/prefs), then re-run." >&2; exit 4; }

step "4. settings LibreWolf changed ($old -> $new)"
if [ -f /tmp/veil-old-librewolf.cfg ]; then
  python3 veil/tools/pref_diff.py /tmp/veil-old-librewolf.cfg "$new/lw/librewolf.cfg"
else
  echo "(no old tree to compare with)"
fi

[ $build = 1 ] || { echo; echo "Checks passed. Build with: (cd $new && ./mach build)"; exit 0; }
step "5. build and test"
(source env.sh && cd "$new" && caffeinate -i ./mach build > ../build-rebase.log 2>&1) ||
  { tail -30 build-rebase.log; echo "Build failed; full log in build-rebase.log" >&2; exit 5; }
python3 veil/tests/run_all.py
