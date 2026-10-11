#!/usr/bin/env bash
# Record every server the built browser talks to, on a brand-new profile.
#
#   veil/tools/capture.sh <name> <seconds> [url ...]
#
# Starts mitmproxy on 127.0.0.1:8899, makes a fresh profile that sends ALL
# traffic through it and trusts mitmproxy's test CA, launches the browser,
# waits <seconds>, quits it, and writes:
#   veil/captures/<name>.jsonl   every request (host, method, path)
#   veil/captures/<name>.hosts   the distinct hosts, with counts
#   veil/captures/<name>.bypass  any socket NOT going to the proxy (should be empty)
#
# The test profile relaxes certificate pinning to level 1 so mitmproxy can see
# inside Mozilla's pinned hosts. That pref lives only in this throwaway
# profile, never in the shipped build.
set -euo pipefail
name=${1:?name}; secs=${2:?seconds}; shift 2
root=$(cd "$(dirname "$0")/../.." && pwd)
src=$(ls -d "$root"/librewolf-*-*/ | head -1)
obj=$(ls -d "$src"obj-*/ | head -1)
app="$obj/dist/LibreWolf.app/Contents/MacOS/librewolf"
out="$root/veil/captures"; mkdir -p "$out"
# VEIL_PROFILE=<dir> reuses (and keeps) a profile, to see a second launch;
# otherwise a throwaway one is made. VEIL_EXPIRE_TIMERS=1 backdates every
# background timer (update checks, list refreshes) so they all fire now
# instead of hours from now.
prof=${VEIL_PROFILE:-$(mktemp -d /tmp/veil-prof.XXXXXX)}
keep=${VEIL_PROFILE:+1}
port=8899

mitmdump="$root/.venv-mitm/bin/mitmdump"   # made by veil/tools/setup-mitm.sh
# First run: mitmproxy writes its test CA to ~/.mitmproxy when it starts.
if [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; then
  "$mitmdump" -q -p $port & p=$!
  for _ in $(seq 30); do [ -f ~/.mitmproxy/mitmproxy-ca-cert.pem ] && break; sleep 1; done
  kill $p; wait $p 2>/dev/null || true
fi

rm -f "$out/$name.jsonl"
VEIL_CAPTURE_OUT="$out/$name.jsonl" "$mitmdump" -q -p $port \
  -s "$root/veil/tools/log_hosts.py" --set ssl_insecure=true >"$out/$name.mitm.log" 2>&1 &
mitm=$!
trap 'kill $mitm 2>/dev/null || true' EXIT
sleep 2

# Trust the test CA in this profile only.
[ -f "$prof/cert9.db" ] || (cd "$obj/dist/bin" && ./certutil -N -d "sql:$prof" --empty-password && \
  ./certutil -A -d "sql:$prof" -n veil-capture -t "C,," -i ~/.mitmproxy/mitmproxy-ca-cert.pem)

cat >"$prof/user.js" <<JS
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", $port);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", $port);
user_pref("network.proxy.no_proxies_on", "");
user_pref("network.proxy.allow_hijacking_localhost", true);
user_pref("security.cert_pinning.enforcement_level", 1);
JS
if [ "${VEIL_EXPIRE_TIMERS:-}" = 1 ] && [ -f "$prof/prefs.js" ]; then
  grep -o 'app\.update\.lastUpdateTime\.[^"]*' "$prof/prefs.js" | sort -u | while read -r k; do
    echo "user_pref(\"$k\", 1);" >>"$prof/user.js"
  done
  echo "user_pref(\"services.settings.last_update_seconds\", 1);" >>"$prof/user.js"
  echo "backdated $(grep -c lastUpdateTime "$prof/user.js") timers"
fi

"$app" -no-remote -profile "$prof" "$@" >"$out/$name.browser.log" 2>&1 &
br=$!
tree() { echo "$1"; for c in $(pgrep -P "$1" || true); do tree "$c"; done; }
: >"$out/$name.bypass"
end=$((SECONDS + secs))
while [ $SECONDS -lt $end ] && kill -0 $br 2>/dev/null; do
  # Every process of this profile, every internet socket that is not the proxy.
  for p in $(tree $br); do
    lsof -nP -a -p "$p" -i 2>/dev/null | awk 'NR>1' | grep -v "127.0.0.1:$port" | grep -v "LISTEN" >>"$out/$name.bypass" || true
  done
  sleep 2
done
kill -TERM $br 2>/dev/null || true; sleep 5; kill -9 $(tree $br) 2>/dev/null || true; pkill -9 -f "$prof" 2>/dev/null || true
sleep 1
sort -u "$out/$name.bypass" -o "$out/$name.bypass"
python3 -c '
import json,sys,collections
c=collections.Counter(); f=collections.Counter()
for l in open(sys.argv[1]):
    r=json.loads(l)
    (c if r["kind"]=="request" else f)[r["host"]]+=1
for h,n in c.most_common(): print(f"{n:5d}  {h}")
for h,n in f.most_common(): print(f"{n:5d}  {h}  (TLS refused)")
' "$out/$name.jsonl" >"$out/$name.hosts" 2>/dev/null || : >"$out/$name.hosts"
[ -n "$keep" ] || rm -rf "$prof"
echo "== $name: hosts contacted"; cat "$out/$name.hosts"
echo "== sockets that skipped the proxy:"; cat "$out/$name.bypass"
