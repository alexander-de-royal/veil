"""mitmproxy addon: one JSON line per request the browser makes.

Used by capture.sh. Records the host, method and path of every request, and
every TLS handshake that failed (a pinned host refusing our test CA shows up
there instead of as a request, so it would otherwise be invisible).
"""
import json
import os
import time

OUT = os.environ.get("VEIL_CAPTURE_OUT", "capture.jsonl")


def _write(rec):
    rec["t"] = round(time.time(), 2)
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def request(flow):
    r = flow.request
    _write({"kind": "request", "method": r.method, "host": r.pretty_host,
            "path": r.path[:300], "len": len(r.raw_content or b"")})


def tls_failed_client(data):
    _write({"kind": "tls_failed", "host": data.context.client.sni or "?",
            "error": str(data.conn.error)[:200]})
