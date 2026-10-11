#!/usr/bin/env bash
# Packet-level check, no proxy: what does the browser contact when nothing is
# steering it? Catches anything that would ignore proxy settings, which the
# mitmproxy audit cannot see.
#
#   sudo veil/tools/pcap.sh [seconds]      (default 300)
#
# Uses macOS's tcpdump on the pktap interface (-k), which tags every packet
# with the PROCESS that sent it, so other apps on the Mac are filtered out.
# Writes veil/captures/pcap.pcapng (open it in Wireshark if you like) and
# prints every remote address the browser's processes talked to, plus the DNS
# names the system resolved during the run (DNS is sent by macOS's resolver,
# not the browser, so that list includes other apps too).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
secs=${1:-300}
root=$(cd "$(dirname "$0")/../.." && pwd)
src=$(ls -d "$root"/librewolf-*-*/ | head -1); obj=$(ls -d "$src"obj-*/ | head -1)
app="$obj/dist/LibreWolf.app/Contents/MacOS/librewolf"
user=${SUDO_USER:?run via sudo from your account}
out="$root/veil/captures"; pcap="$out/pcap.pcapng"
prof=$(sudo -u "$user" mktemp -d /tmp/veil-pcap.XXXXXX)

tcpdump -i pktap,all -k -w "$pcap" -q 'not host 127.0.0.1 and not host ::1' 2>/dev/null & td=$!
sleep 2
sudo -u "$user" "$app" -no-remote -profile "$prof" >/dev/null 2>&1 & br=$!
sleep "$secs"
kill -TERM $br 2>/dev/null || true; sleep 5; pkill -9 -f "$prof" 2>/dev/null || true
kill $td; wait $td 2>/dev/null || true
chown "$user" "$pcap"; rm -rf "$prof"

echo "== remote endpoints, browser processes only (count  proc  address.port)"
tcpdump -r "$pcap" -k -n -q 2>/dev/null \
  | grep -iE 'proc (librewolf|plugin-contain)' \
  | grep -oE 'proc [^,]+|> [0-9a-f.:]+\.[0-9]+' | paste - - \
  | sed -E 's/proc ([^:]+):[0-9]+:?/\1/; s/> //' | sort | uniq -c | sort -rn
echo "== DNS names resolved system-wide during the run"
tcpdump -r "$pcap" -n 'udp port 53' 2>/dev/null | grep -oE '(A|AAAA|HTTPS)\? [^ ]+' | sort | uniq -c | sort -rn
