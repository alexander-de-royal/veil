#!/usr/bin/env python3
"""Collect the fingerprint page's attributes under different machine setups.

    python3 veil/tests/fp_collect.py            prints a comparison table

Each setup is a brand-new profile. "other" changes things about the machine
that a uniform fingerprint must NOT reveal: the timezone (TZ), the OS locale
variables, and the window size. (A language the user explicitly picks in
Settings is their choice and does reach sites; see test_fingerprint.py.)
"""
import json
import pathlib
import time

from harness import Browser, Server

PAGE = (pathlib.Path(__file__).parent / "fingerprint.html").read_text()
OTHER = {"env": {"TZ": "Asia/Tokyo", "LANG": "ja_JP.UTF-8", "LC_ALL": "ja_JP.UTF-8"}, "prefs": {}, "size": (1237, 740)}


def collect(srv, rfp=True, other=False, extra_prefs=None):
    prefs = dict(extra_prefs or {})
    if not rfp:
        prefs["privacy.resistFingerprinting"] = False
    if other:
        prefs.update(OTHER["prefs"])
    b = Browser(extra_prefs=prefs, env=OTHER["env"] if other else None)
    try:
        if other:
            b.chrome_js("window.resizeTo(arguments[0], arguments[1])", *OTHER["size"])
        else:
            b.chrome_js("window.resizeTo(1400, 900)")
        time.sleep(1)
        srv.headers.clear()
        b.go(srv.url("localhost", "/fingerprint.html"))
        fp = b.wait("return window.fp", 30) or {"error": "no result"}
        fp["acceptLanguage"] = next((h.get("Accept-Language") for p, h in srv.headers if p == "/fingerprint.html"), None)
        return fp
    finally:
        b.close()


def flat(fp):
    out = {}
    for k, v in fp.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    srv = Server()
    srv.page("/fingerprint.html", PAGE)
    runs = {name: flat(collect(srv, **kw)) for name, kw in {
        "rfp": dict(rfp=True), "rfp-other": dict(rfp=True, other=True),
        "off": dict(rfp=False), "off-other": dict(rfp=False, other=True)}.items()}
    srv.close()
    keys = sorted(set().union(*runs.values()))
    print(f"{'attribute':26} {'same?':6} rfp  |  rfp-other  ||  off  |  off-other")
    for k in keys:
        v = [str(runs[n].get(k))[:60] for n in runs]
        print(f"{k:26} {'rfp ok' if v[0] == v[1] else 'LEAKS':6} {v[0]}  |  {v[1]}  ||  {v[2]}  |  {v[3]}")
    json.dump(runs, open(pathlib.Path(__file__).parents[1] / "captures/fingerprint.json", "w"), indent=1)
