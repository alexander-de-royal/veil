#!/usr/bin/env python3
"""Phase 5: does every Veil user present the same fingerprint?

    python3 veil/tests/test_fingerprint.py

Collects ~45 attributes (fingerprint.html) on a brand-new profile twice: once
as this machine, once pretending to be a different one (Tokyo timezone,
Japanese OS locale, a different window size). Everything must match except:
  - the page size, which letterboxing rounds to a few common sizes (checked:
    two different windows of similar size must report the SAME size)
  - canvas reads, which Firefox fills with fresh random data each time when
    a site has not been allowed to read the canvas (there is no pref for a
    uniform blank image in Firefox 157; it would need a source patch)
Also checks fixed values (UTC, en-US, coarse timers) and that fonts the user
installed are invisible to pages.
"""
import os
import pathlib

from fp_collect import OTHER, flat
from harness import Browser, Results, Server

PAGE = (pathlib.Path(__file__).parent / "fingerprint.html").read_text()
VARIES_BY_DESIGN = {"canvas", "inner", "outer", "screen"}


def user_font_families(b):
    """Font families the browser knows that come from your own font folder."""
    files = [f.lower().replace(" ", "")
             for d in ("~/Library/Fonts", "~/.local/share/fonts", "~/.fonts")  # macOS, Linux
             if os.path.isdir(os.path.expanduser(d)) for f in os.listdir(os.path.expanduser(d))]
    known = b.chrome_js('return Cc["@mozilla.org/gfx/fontenumerator;1"].getService(Ci.nsIFontEnumerator).EnumerateAllFonts()')
    return [f for f in known if any(x.startswith(f.lower().replace(" ", "")) for x in files)]


def collect(srv, size, env=None, fonts=()):
    b = Browser(env=env)
    try:
        b.chrome_js("window.resizeTo(arguments[0], arguments[1])", *size)
        fams = user_font_families(b)
        srv.headers.clear()
        b.go(srv.url("localhost", "/fingerprint.html#fonts=" + ",".join(fams)))
        fp = b.wait("return window.fp", 30) or {"error": "no result"}
        fp["acceptLanguage"] = next((h.get("Accept-Language") for p, h in srv.headers if p == "/fingerprint.html"), None)
        return flat(fp), fams
    finally:
        b.close()


def main():
    r, srv = Results(), Server()
    srv.page("/fingerprint.html", PAGE)
    here, fams = collect(srv, (1400, 900))
    there, _ = collect(srv, OTHER["size"], OTHER["env"])
    # Mid-step on purpose: page sizes round in 100 px steps, so a window that
    # crosses a step boundary legitimately lands in the next one.
    near, _ = collect(srv, (OTHER["size"][0] + 43, OTHER["size"][1] + 20), OTHER["env"])

    for k in sorted(set(here) | set(there)):
        if k in VARIES_BY_DESIGN:
            continue
        r.check(f"same on both machines: {k}", here.get(k) == there.get(k),
                "" if here.get(k) == there.get(k) else f"{here.get(k)!r} vs {there.get(k)!r}")

    r.check("letterboxing: similar windows report the same page size", there["inner"] == near["inner"],
            f"{OTHER['size']} -> {there['inner']}, +43x20 -> {near['inner']}")
    r.check("screen size reveals nothing beyond the page size", here["screen"].startswith(here["inner"]), here["screen"])
    r.check("timezone is UTC", here["tzOffsetJan"] == 0 and here["tzOffsetJul"] == 0, here["timeZone"])
    r.check("languages are en-US", here["languages"] == "en-US,en" and here["intlLocale"] == "en-US",
            f"{here['languages']} / {here['intlLocale']}")
    r.check("Accept-Language header is en-US", (here["acceptLanguage"] or "").startswith("en-US,en"), here["acceptLanguage"])
    r.check("timers coarsened to >= 16 ms", (here["timerResolutionMs"] or 0) >= 16, f"{here['timerResolutionMs']} ms")
    visible = [f for f in fams if f in here["fonts"].split(",")]
    r.check("fonts you installed are invisible to pages", not visible,
            f"{len(fams)} user fonts, visible: {visible}" if fams else "no user fonts on this machine to test")
    r.check("canvas reads are randomized, not the real image", here["canvas"] != there["canvas"])
    srv.close()
    r.done()


if __name__ == "__main__":
    main()
