#!/usr/bin/env python3
"""Run EFF's Cover Your Tracks (coveryourtracks.eff.org) in the built browser.

    python3 veil/tests/cover_your_tracks.py [--compare]

Opens a VISIBLE window (headless has no GPU, so WebGL and screen would not
be real), starts the test, waits for the verdict, and prints the summary and
the per-attribute table. Saves the full text to veil/captures/cyt-<label>.txt.
--compare also runs it with resistFingerprinting off, for contrast.

This sends your fingerprint to EFF; that is the point of the test. Note the
browser is under automation, so navigator.webdriver is true during the run;
Cover Your Tracks does not list that attribute, but a real tracker could.
"""
import pathlib
import sys
import time

from harness import Browser

OUT = pathlib.Path(__file__).resolve().parents[1] / "captures"


def run(label, prefs=None):
    b = Browser(headless=False, extra_prefs=prefs)
    try:
        b.chrome_js("window.resizeTo(1400, 900)")
        b.go("https://coveryourtracks.eff.org/kcarter?aat=1")
        text = None
        for _ in range(120):
            time.sleep(1)
            t = b.js("return document.body ? document.body.innerText : ''") or ""
            if "bits of identifying information" in t or "Our tests indicate" in t and "fingerprint" in t:
                time.sleep(3)
                text = b.js("return document.body.innerText")
                break
        text = text or b.js("return document.body.innerText") or ""
        (OUT / f"cyt-{label}.txt").write_text(text)
        return text
    finally:
        b.close()


def summary(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    keep = [l for l in lines if any(w in l for w in ("Our tests indicate", "unique", "bits of identifying",
            "protection against", "one in", "Blocking tracking", "invisible trackers", "fingerprint"))]
    return "\n".join(dict.fromkeys(keep))


if __name__ == "__main__":
    runs = [("veil", None)] + ([("rfp-off", {"privacy.resistFingerprinting": False})] if "--compare" in sys.argv else [])
    for label, prefs in runs:
        print(f"===== {label} =====", flush=True)
        print(summary(run(label, prefs)), flush=True)
