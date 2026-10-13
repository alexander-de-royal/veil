#!/usr/bin/env python3
"""Phase 4: are sites kept apart, and is their data gone after you quit?

    python3 veil/tests/test_isolation.py

Uses four made-up sites (network.dns.localDomains points them at the local
test server): site-a.test and site-b.test are websites you visit,
embed.test is a third party embedded in both, keep.test is a site you have
told the browser to remember (a "Manage Exceptions" Allow). The
clear-on-exit part uses localhost (cleared) and 127.0.0.1 (excepted) instead,
because only those count as secure over http, and the Cache API needs that.

Test-only profile changes: those hostnames, and HTTPS-only mode off so plain
http works for them. Neither affects isolation or clearing.
"""
import tempfile
import time

from harness import Browser, Results, Server

SITES = ["site-a.test", "site-b.test", "embed.test", "keep.test"]
PREFS = {"network.dns.localDomains": ",".join(SITES), "dom.security.https_only_mode": False}

DATA = """<script>
const mode = new URLSearchParams(location.search).get("mode");
(async () => {
  if (mode === "write") {
    document.cookie = "veil=1; max-age=31536000; path=/";
    localStorage.setItem("veil", "1");
  }
  const db = await new Promise((res, rej) => {
    const r = indexedDB.open("veil", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("s");
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  if (mode === "write") await new Promise(res => {
    const t = db.transaction("s", "readwrite"); t.objectStore("s").put("1", "k"); t.oncomplete = res;
  });
  const idb = await new Promise(res => {
    const q = db.transaction("s").objectStore("s").get("k");
    q.onsuccess = () => res(q.result ?? null); q.onerror = () => res("error");
  });
  let cache = "unavailable";
  if (self.caches) {
    const c = await caches.open("veil");
    if (mode === "write") await c.put("/veil-cached", new Response("1"));
    const hit = await c.match("/veil-cached");
    cache = hit ? await hit.text() : null;
  }
  window.state = { cookie: document.cookie, ls: localStorage.getItem("veil"), idb, cache };
})().catch(e => { window.state = { error: String(e) }; });
</script>"""

EMBED = """<script>
const m = new URLSearchParams(location.search).get("mode");
if (m.startsWith("write:")) localStorage.setItem("veil", m.slice(6));
parent.postMessage({ ls: localStorage.getItem("veil") }, "*");
</script>"""


def main():
    r, srv = Results(), Server()
    u = srv.url
    srv.page("/data.html", DATA)
    srv.page("/embed.html", EMBED)
    srv.page("/host.html", """<script>addEventListener("message", e => { window.got = e.data; });
      document.write('<iframe src="%s/embed.html' + location.search + '"></iframe>');</script>"""
             % u("embed.test", "").rstrip("/"))
    srv.page("/cached.js", "window.cachedLoaded = 1;", {"Content-Type": "text/javascript", "Cache-Control": "max-age=3600"})
    srv.page("/cache.html", '<script src="%s"></script>' % u("embed.test", "/cached.js"))

    # ===================== isolation =====================================
    b = Browser(extra_prefs=PREFS)
    try:
        b.go(u("site-a.test", "/host.html?mode=read"))
        b.wait("return window.got")
        procs = b.chrome_js("""
          return gBrowser.selectedBrowser.browsingContext.getAllBrowsingContextsInSubtree()
            .map(c => [c.currentWindowGlobal?.documentPrincipal?.origin, c.currentWindowGlobal?.osPid]);""")
        pids = {o.split("://")[1].split(":")[0]: p for o, p in procs if o}
        r.check("embedded site runs in a separate process from the page (site isolation)",
                len(pids) == 2 and pids.get("site-a.test") != pids.get("embed.test"), str(pids))

        def frame_ls(site, mode):
            b.go(u(site, f"/host.html?mode={mode}"))
            return (b.wait("return window.got") or {}).get("ls", "no answer")

        a = frame_ls("site-a.test", "write:fromA")
        r.check("embedded site can store data under site-a (control)", a == "fromA", repr(a))
        bb = frame_ls("site-b.test", "read")
        r.check("same embedded site under site-b cannot see it (storage partitioned)", bb is None, repr(bb))
        a2 = frame_ls("site-a.test", "read")
        r.check("back under site-a the data is still there (partitioned, not blocked)", a2 == "fromA", repr(a2))
        b.go(u("embed.test", "/embed.html?mode=write:top"))
        bb = frame_ls("site-b.test", "read")
        r.check("embedded site cannot reach its own first-party storage", bb is None, repr(bb))

        hits = lambda: sum(1 for h, p in srv.hits if p == "/cached.js")
        b.go(u("site-a.test", "/cache.html")); b.wait("return window.cachedLoaded")
        b.go(u("site-a.test", "/cache.html")); b.wait("return window.cachedLoaded")
        after_a = hits()
        b.go(u("site-b.test", "/cache.html")); b.wait("return window.cachedLoaded")
        after_b = hits()
        r.check("cached file reused within site-a (control)", after_a == 1, f"{after_a} fetches")
        r.check("cache not shared with site-b (cache partitioned)", after_b == after_a + 1,
                f"{after_b - after_a} new fetches from site-b")
    finally:
        b.close()

    # ===================== clear on exit ===================================
    # localhost and 127.0.0.1 here, not the .test names: they count as secure
    # contexts over plain http, which the Cache API requires.
    prof = tempfile.mkdtemp(prefix="veil-exit.")

    def state(b, site, mode):
        b.go(u(site, f"/data.html?mode={mode}"))
        return b.wait("return window.state", 15) or {"error": "no answer"}

    stored = {"cookie": "veil=1", "ls": "1", "idb": "1", "cache": "1"}
    empty = {"cookie": "", "ls": None, "idb": None, "cache": None}

    b = Browser(profile=prof, extra_prefs=PREFS)
    b.chrome_js("""const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(arguments[0]);
                   // What Settings > Cookies and Site Data > Manage Exceptions > Allow sets
                   // (Firefox 157; older versions used a "cookie" ALLOW permission).
                   Services.perms.addFromPrincipal(p, "persist-data-on-shutdown", Services.perms.ALLOW_ACTION);""",
                u("127.0.0.1", "").rstrip("/"))
    s_a, s_k = state(b, "localhost", "write"), state(b, "127.0.0.1", "write")
    r.check("site data written (control)", s_a == stored and s_k == stored, f"{s_a} {s_k}")
    time.sleep(3)
    b.quit()

    b = Browser(profile=prof, extra_prefs=PREFS)
    s = state(b, "localhost", "read")
    r.check("after quitting: cookies, localStorage, IndexedDB, Cache API gone", s == empty, str(s))
    s = state(b, "127.0.0.1", "read")
    r.check("after quitting: a site with an exception keeps its data", s == stored, str(s))
    kept = b.chrome_js("""const done = arguments[arguments.length - 1];
      const { PlacesUtils } = ChromeUtils.importESModule("resource://gre/modules/PlacesUtils.sys.mjs");
      PlacesUtils.history.hasVisits(arguments[0]).then(done);""", u("localhost", "/data.html?mode=write"), asynchronous=True)
    print(f"info  browsing history kept after quitting: {kept} (LibreWolf default)")

    state(b, "localhost", "write")
    time.sleep(5)  # let the cookie database reach the disk, so a crash has something to leave behind
    b.crash()
    b = Browser(profile=prof, extra_prefs=PREFS)
    s = state(b, "localhost", "read")
    r.check("after a crash: data cleared on the next launch", s == empty, str(s))
    b.profile_cleanup = True
    b.keep = False
    b.close()
    srv.close()
    r.done()


if __name__ == "__main__":
    main()
