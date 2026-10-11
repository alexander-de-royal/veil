#!/usr/bin/env python3
"""Phase 3: is tracker blocking actually in effect in the built browser?

    python3 veil/tests/test_tracking.py

Runs headless on a brand-new profile, so it also checks the first-launch
state: uBlock Origin must already be on before any download.

"localhost" and "127.0.0.1" are different sites to the browser, which lets
one local server play both a website and a third party embedded in it.
"""
import time

from harness import Browser, Results, Server

UBO = "uBlock0@raymondhill.net"
TRACKERS = {
    # (url, what should happen)
    "google-analytics.com": "https://www.google-analytics.com/analytics.js",
    "googletagmanager.com": "https://www.googletagmanager.com/gtag/js?id=G-TEST",
    "facebook pixel": "https://connect.facebook.net/en_US/fbevents.js",
    "doubleclick ads": "https://securepubads.g.doubleclick.net/tag/js/gpt.js",
    "adsbygoogle": "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js",
    "hotjar": "https://static.hotjar.com/c/hotjar-12345.js?sv=6",
}
CONTROL = "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"


def leaked(b, srv, tag):
    """Load every tracker on one page; return the names that reached the network."""
    srv.page(f"/leak-{tag}.html", "".join(f'<script src="{u}"></script>' for u in TRACKERS.values()))
    b.watch_network()
    b.go(srv.url("localhost", f"/leak-{tag}.html"))
    time.sleep(1)
    seen = {s.split("?")[0] for s in b.network_seen()}
    return [n for n, u in TRACKERS.items() if u.split("?")[0] in seen]


def main():
    r, srv = Results(), Server()
    started = time.time()
    b = Browser()
    try:
        # -- configuration actually live, not just written in a file ---------
        for name, want in [
            ("browser.contentblocking.category", "strict"),
            ("network.cookie.cookieBehavior", 5),
            ("network.cookie.cookieBehavior.optInPartitioning", True),
            ("privacy.query_stripping.enabled", True),
            ("privacy.query_stripping.strip_on_share.enabled", True),
            ("privacy.bounceTrackingProtection.mode", 1),
            ("privacy.trackingprotection.enabled", True),
        ]:
            got = b.pref(name)
            r.check(f"pref {name} = {want!r}", got == want, f"got {got!r}")

        # -- uBlock Origin present on first launch, before any download ------
        ubo = b.chrome_js("""
          const done = arguments[arguments.length - 1];
          const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
          AddonManager.getAddonByID(arguments[0]).then(a => done(a && {
            version: a.version, active: a.isActive, location: a.location?.name || a.installTelemetryInfo?.source || "" }));
        """, UBO, asynchronous=True)
        r.check("uBlock Origin installed and active at first launch",
                bool(ubo and ubo["active"]),
                f"{ubo} after {time.time() - started:.0f}s")

        # -- the first-launch gap ---------------------------------------------
        # A brand-new profile has no tracker lists yet: Firefox downloads its
        # own, and uBlock Origin compiles its bundled ones. Until then trackers
        # get through. Measured (~16 s in Oct 2026); fail if it grows.
        for i in range(60):
            if not leaked(b, srv, f"gap{i}"):
                break
            time.sleep(1)
        gap = time.time() - started
        r.check("first-launch blocking gap under 30 s", gap < 30, f"blocking began {gap:.0f}s after launch")

        # -- third-party cookies ---------------------------------------------
        srv.page("/top.html", """<script>document.cookie = "veil1p=1; path=/";
          window.firstParty = document.cookie;
          addEventListener("message", e => { window.thirdParty = e.data; });</script>
          <iframe src="%s"></iframe>""" % srv.url("127.0.0.1", "/frame.html"))
        srv.page("/frame.html", """<script>
          document.cookie = "veil3p=1; path=/";
          parent.postMessage("cookie=" + document.cookie, "*");</script>""")
        b.go(srv.url("localhost", "/top.html"))
        r.check("first-party cookie set (control)", b.js("return window.firstParty") == "veil1p=1",
                b.js("return window.firstParty"))
        third = b.wait("return window.thirdParty")
        r.check("third-party cookie rejected in embedded frame", third == "cookie=", repr(third))

        # -- tracking parameters stripped on navigation ----------------------
        # Cross-site, like clicking a link in an email or a search result.
        srv.page("/start.html", "<p>start</p>")
        srv.page("/land.html", "<p>landed</p>")
        params = "fbclid=AAA&gclid=BBB&msclkid=CCC&utm_source=news&utm_campaign=x&mc_eid=DDD&keep=1"
        # utm_* is stripped by uBlock Origin's "AdGuard URL Tracking
        # Protection" list, which is NOT inside the bundled add-on and arrives
        # by download, so allow it up to a minute on a new profile.
        t_list = time.time()
        for i in range(30):
            b.go(srv.url("127.0.0.1", "/start.html"))
            b.js("location.href = arguments[0]", srv.url("localhost", f"/land.html?{params}&try={i}"))
            b.wait("return location.pathname === '/land.html'")
            time.sleep(0.5)
            sent = [p for h, p in srv.hits if p.startswith("/land.html")]
            query = sent[-1].partition("?")[2] if sent else "(never arrived)"
            if "utm_" not in query:
                break
            time.sleep(1.5)
        print(f"info  utm_* stripping available {time.time() - t_list:.0f}s after the gap closed")
        for p in ["fbclid", "gclid", "msclkid", "mc_eid", "utm_source", "utm_campaign"]:
            r.check(f"strips {p}", f"{p}=" not in query, f"server received ?{query}")
        r.check("keeps ordinary parameters (keep=1)", "keep=1" in query, f"?{query}")

        # -- trackers blocked, ordinary CDN not --------------------------------
        tags = "".join(
            f'<script src="{u}" onload="R[{name!r}]=\'loaded\'" onerror="R[{name!r}]=\'blocked\'"></script>'
            for name, u in {**TRACKERS, "control": CONTROL}.items())
        srv.page("/trackers.html", f"<script>window.R = {{}}</script>{tags}")
        b.watch_network()
        b.go(srv.url("localhost", "/trackers.html"))
        b.wait(f"return Object.keys(window.R).length >= {len(TRACKERS) + 1}", 30)
        seen = b.network_seen()
        reached = lambda u: any(s.split("?")[0] == u.split("?")[0] for s in seen)
        r.check("ordinary CDN script fetched from network (control)", reached(CONTROL))
        for name, u in TRACKERS.items():
            r.check(f"blocks {name}", not reached(u), "request reached the server" if reached(u) else "")
    finally:
        b.close()
        srv.close()
    r.done()


if __name__ == "__main__":
    main()
