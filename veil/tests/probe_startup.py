#!/usr/bin/env python3
"""How long after launch does tracker blocking start working?

    python3 veil/tests/probe_startup.py

Loads a page of tracker scripts every 2 s from the moment the browser
answers, on a brand-new profile and then on a second launch of the same
profile, and prints which trackers still reached the network each time.
"""
import tempfile
import time

from harness import Browser, Server
from test_tracking import TRACKERS


def probe(label, srv, profile):
    t0 = time.time()
    b = Browser(profile=profile)
    print(f"== {label}: Marionette up after {time.time() - t0:.1f}s")
    try:
        tags = "".join(f'<script src="{u}"></script>' for u in TRACKERS.values())
        for i in range(45):
            srv.page(f"/t{i}.html", tags)
            b.watch_network()
            b.go(srv.url("localhost", f"/t{i}.html?n={i}"))
            time.sleep(1)
            seen = {s.split("?")[0] for s in b.network_seen()}
            leaked = [n for n, u in TRACKERS.items() if u.split("?")[0] in seen]
            print(f"  t={time.time() - t0:5.1f}s  leaked {len(leaked)}/{len(TRACKERS)}  {', '.join(leaked)}", flush=True)
            if not leaked and i >= 2:
                break
            time.sleep(1)
    finally:
        b.close()


srv = Server()
prof = tempfile.mkdtemp(prefix="veil-probe.")
probe("first launch (new profile)", srv, prof)
probe("second launch (same profile)", srv, prof)
srv.close()
