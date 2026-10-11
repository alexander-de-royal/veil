#!/usr/bin/env python3
"""Compare two audits host by host.

    python3 veil/tools/compare.py baseline veil

Reads veil/captures/<tag>-{first,timers,browse}.jsonl and prints, per host,
how many requests each audit made and an example path, so a removed
phone-home shows up as "N -> 0". Hosts belonging to the sites the browse
step visited are listed separately: those are the user's own traffic.
"""
import collections
import json
import pathlib
import sys

CAP = pathlib.Path(__file__).resolve().parent.parent / "captures"
SITES = ("example.com", "wikipedia.org", "wikimedia.org")
PHASES = ("first", "timers", "browse")


def load(tag):
    hosts = collections.defaultdict(lambda: {"n": 0, "path": "", "phases": set()})
    for ph in PHASES:
        f = CAP / f"{tag}-{ph}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            r = json.loads(line)
            h = hosts[r["host"] + (" (TLS refused)" if r["kind"] != "request" else "")]
            h["n"] += 1
            h["phases"].add(ph)
            h["path"] = h["path"] or r.get("path", "")
    return hosts


def main(a, b=None):
    A, B = load(a), (load(b) if b else {})
    rows = sorted(set(A) | set(B), key=lambda h: (any(s in h for s in SITES), h))
    print(f"{'host':48} {a:>9} {b or '':>9}  phases / example path")
    for h in rows:
        site = any(s in h for s in SITES)
        x, y = A.get(h, {"n": 0, "phases": set(), "path": ""}), B.get(h, {"n": 0, "phases": set(), "path": ""})
        ph = ",".join(sorted(x["phases"] | y["phases"]))
        print(f"{h[:48]:48} {x['n']:>9} {y['n'] if b else '':>9}  {'[site] ' if site else ''}{ph}  {(x['path'] or y['path'])[:70]}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
