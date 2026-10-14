"""Phase 6: HTTPS-only, encrypted DNS and WebRTC, checked in the real browser.

    python3 veil/tests/test_network.py

Needs the internet (example.com, badssl.com, Wikipedia, GitHub, Cloudflare).
What it checks:
  - http:// addresses are upgraded to https://, and a site with no https
    gets the "continue to HTTP?" page instead of a silent plaintext load,
    and the address you typed never goes out unencrypted on the way;
  - an https page never fetches anything over plain http (mixed content);
  - every hostname the browser looks up goes over DNS-over-HTTPS, and the
    TLS handshake hides which site you're visiting (Encrypted Client Hello);
  - WebRTC never shows a page your local IP addresses, and only offers the
    network interface your traffic actually uses (the VPN, if you use one).
"""
import re
import socket
import time

from harness import Browser, Results, Server

r = Results()
srv = Server()
# The harness exempts local addresses from HTTPS-only (for its own test
# server); here we want the shipped behaviour, where they're upgraded too.
b = Browser(extra_prefs={"dom.security.https_only_mode.upgrade_local": True})

# ---------------------------------------------------------------- prefs
for name, want in [
    ("dom.security.https_only_mode", True),
    ("network.trr.mode", 3),
    ("network.dns.echconfig.enabled", True),
    ("media.peerconnection.ice.default_address_only", True),
    ("media.peerconnection.ice.obfuscate_host_addresses", True),
]:
    got = b.pref(name)
    r.check(f"pref {name} = {want}", got == want, f"is {got}")

# ---------------------------------------------------------------- HTTPS-only
b.go("http://example.com/")
r.check("http:// address upgraded to https://", b.js("return location.href").startswith("https://"),
        b.js("return location.href"))

# An http-only site: our test server, on this machine's network address.
# Nothing answers https on its port.
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
    u.connect(("192.0.2.1", 9))  # no packet is sent; this just picks the route
    lan = u.getsockname()[0]
srv.page("/private/page", "<title>plain</title>")
t = time.time()
doc = b.go(srv.url(lan, "/private/page?q=secret")) or b.js("return document.documentURI")
r.check("site without https gets the 'continue to HTTP?' page", doc.startswith("about:httpsonlyerror"),
        f"{doc[:40]} after {time.time() - t:.0f}s")
# Firefox's background probe may ask http://<host>/ (no path, no cookies), to
# show that page in seconds rather than after a 90 s timeout.
paths = [p for h, p in srv.hits]
r.check("the page's path never goes out in plaintext", "/private/page?q=secret" not in paths,
        f"plaintext requests: {paths}")

b.watch_network()
for url in ["https://mixed.badssl.com/", "https://mixed-script.badssl.com/"]:
    b.go(url)
time.sleep(2)
plain = [u for u in b.network_seen() if u.startswith("http://")]
r.check("https pages fetch nothing over plain http (mixed content)", not plain, ", ".join(plain[:3]))

# ---------------------------------------------------------------- DNS
RESOLVE = """
  const [host, done] = arguments;
  Services.dns.asyncResolve(host, Ci.nsIDNSService.RESOLVE_TYPE_DEFAULT,
    Ci.nsIDNSService.RESOLVE_BYPASS_CACHE, null, {
      onLookupComplete(req, rec, status) {
        if (!Components.isSuccessCode(status)) return done({error: status});
        rec.QueryInterface(Ci.nsIDNSAddrRecord);
        done({trr: rec.IsTRR(), mode: rec.effectiveTRRMode, skip: rec.trrSkipReason});
      }
    }, Services.tm.mainThread, {});
"""
for host in ["wikipedia.org", "github.com", "news.ycombinator.com"]:
    res = b.chrome_js(RESOLVE, host, asynchronous=True)
    r.check(f"{host} looked up over DNS-over-HTTPS", res.get("trr") is True, str(res))

DASH = """
  const done = arguments[0];
  Cc["@mozilla.org/network/dashboard;1"].getService(Ci.nsIDashboard)
    .requestDNSInfo({ onDashboardDataAvailable(d) {
      done(d.entries.map(e => [e.hostname, e.trr, e.type, (e.hostaddr || []).length]));
    }});
"""
resolver = re.sub(r"^https://([^/]+).*", r"\1", b.pref("network.trr.uri") or "")
# Only address records that resolved to something carry the flag: HTTPS
# records and empty answers (e.g. no IPv6 address) always read "not TRR".
# Firefox's TRR-only mode never uses the system resolver for those either.
plain = sorted({h for h, trr, kind, n in b.chrome_js(DASH, asynchronous=True)
                if kind == 0 and n and not trr and h not in ("localhost", resolver)})
r.check("every site visited above was looked up encrypted", not plain, ", ".join(plain))
print(f"info  the resolver's own name ({resolver}) is looked up once in plain DNS, to find it")

b.go("https://crypto.cloudflare.com/cdn-cgi/trace")
trace = dict(l.split("=", 1) for l in b.js("return document.body.innerText").splitlines() if "=" in l)
r.check("TLS hides which site you visit (Encrypted Client Hello)", trace.get("sni") == "encrypted",
        f"sni={trace.get('sni')}")

# ---------------------------------------------------------------- WebRTC
GATHER = """
  window.cands = null;
  (async () => {
    const pc = new RTCPeerConnection({iceServers: arguments[0]}), c = [];
    pc.createDataChannel("x");
    pc.onicecandidate = e => e.candidate && e.candidate.candidate && c.push(e.candidate.candidate);
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise(ok => {
      pc.onicegatheringstatechange = () => pc.iceGatheringState == "complete" && ok();
      setTimeout(ok, 10000);
    });
    pc.close();
    window.cands = c;
  })();
"""
IP = re.compile(r"^(\d+\.\d+\.\d+\.\d+|[0-9a-f:]*:[0-9a-f:]+)$", re.I)


def gather(servers):
    b.js(GATHER, servers)
    cands = b.wait("return window.cands", 15) or []
    # candidate:<f> <comp> <proto> <prio> <address> <port> typ <type> [raddr <a> ...]
    out = []
    for c in cands:
        f = c.split()
        out.append({"addr": f[4], "type": f[7], "raddr": f[f.index("raddr") + 1] if "raddr" in f else None})
    return out


# A real site: without camera/mic permission Firefox only offers the interface
# that routes to the page's server, so a page on localhost would get nothing.
b.go("https://example.com/")
host = gather([])
raw = [c["addr"] for c in host if IP.match(c["addr"])]
r.check("WebRTC hides your local IP addresses (no camera/mic permission)", host and not raw,
        f"{len(host)} candidates, raw: {raw}" if raw else f"{len(host)} candidates, all *.local names")
ifaces = len({c["addr"] for c in host if c["type"] == "host"})
r.check("WebRTC offers only the interface your traffic uses", 0 < ifaces <= 2,
        f"{ifaces} host addresses (one per IPv4/IPv6 at most)")

stun = gather([{"urls": "stun:stun.cloudflare.com:3478"}])
srflx = [c for c in stun if c["type"] == "srflx"]
leaky = [c["raddr"] for c in srflx if c["raddr"] and c["raddr"] not in ("0.0.0.0", "::")]
r.check("public-IP candidates don't carry your local IP along", not leaky, str(leaky))
pub = sorted({c["addr"] for c in srflx})
print(f"info  public address a STUN server reports: {pub or 'none'} (sites already see it as ip={trace.get('ip')})")

# A site you let use the camera/mic sees real local addresses (calls need
# them); default_address_only keeps that to the one interface you browse on.
b.chrome_js("""
  const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin("https://example.com");
  for (const t of ["camera", "microphone"]) Services.perms.addFromPrincipal(p, t, Services.perms.ALLOW_ACTION);""")
b.go("https://example.com/")
call = [c["addr"] for c in gather([]) if c["type"] == "host"]
v4 = {a for a in call if "." in a and IP.match(a)}
r.check("during a call, only the main interface's address is offered", len(v4) <= 1, ", ".join(sorted(set(call))))


b.close()
srv.close()
r.done()
