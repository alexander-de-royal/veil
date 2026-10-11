#!/usr/bin/env bash
# The phase-2 network audit: three captures on one profile.
#   <tag>-first    first launch, idle 5 min
#   <tag>-timers   second launch with every background timer expired, idle 3 min
#   <tag>-browse   third launch, visiting a few ordinary sites, 2 min
#   veil/tools/audit.sh <tag>
set -euo pipefail
# Stay awake for the whole run (a sleeping Mac stalls the capture).
command -v caffeinate >/dev/null && { caffeinate -i -w $$ & }
tag=${1:?tag}
here=$(dirname "$0")
P=$(mktemp -d /tmp/veil-audit.XXXXXX)
VEIL_PROFILE=$P "$here/capture.sh" "$tag-first" 300
VEIL_PROFILE=$P VEIL_EXPIRE_TIMERS=1 "$here/capture.sh" "$tag-timers" 180
VEIL_PROFILE=$P "$here/capture.sh" "$tag-browse" 120 https://example.com https://en.wikipedia.org/wiki/Web_browser
rm -rf "$P"
