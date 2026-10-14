"""Drive the built browser for Veil's tests. No dependencies beyond Python.

Starts the browser headless on a throwaway profile with Marionette (Firefox's
built-in automation protocol) and a tiny local web server, and gives tests:

    b.go(url)                 navigate and wait for load (returns error page URL)
    b.js(script, *args)       run JS in the page, return its result
    b.chrome_js(script)       run JS with browser privileges (prefs, add-ons)
    b.wait(script, timeout)   poll page JS until it returns something truthy
    srv.url(host, path)       http://<host>:<port><path> on the local server
    srv.page(path, html, headers={...})   serve this body (str or bytes) at path
    b.quit()                  quit normally (runs clear-on-exit)
    b.crash()                 kill -9, like a crash or a force-quit
    srv.hits                  every path the server was asked for, in order

The profile changes only what the tests need to function: the Marionette
port, and letting HTTPS-only mode leave the local test server on http.
Everything else is the build's own configuration.
"""
import contextlib
import http.server
import json
import os
import re
import pathlib
import shutil
import socket
import subprocess
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Keep a Mac awake while tests run: on battery it sleeps through idle waits,
# which shows up as page loads "hanging" for minutes.
if shutil.which("caffeinate"):
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])


def find_app():
    # The tree for the checked-out version; VEIL_TREE=librewolf-x-y picks another.
    name = os.environ.get("VEIL_TREE") or f"librewolf-{(ROOT / 'version').read_text().strip()}-{(ROOT / 'release').read_text().strip()}"
    src = ROOT / name if (ROOT / name).is_dir() else sorted(ROOT.glob("librewolf-*-*/"))[-1]
    objs = sorted(src.glob("obj-*/"))
    if not objs:
        raise SystemExit(f"{src.name} is not built yet: (cd {src.name} && ./mach build)")
    obj = objs[0]
    mac = obj / "dist/LibreWolf.app/Contents/MacOS/librewolf"
    return mac if mac.exists() else obj / "dist/bin/librewolf"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self):
        self.pages, self.hits, self.headers = {}, [], []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append((self.headers.get("Host", ""), self.path))
                outer.headers.append((self.path, dict(self.headers)))
                entry = outer.pages.get(self.path.split("?")[0])
                if entry is None:
                    self.send_response(404); self.end_headers(); return
                body, headers = entry
                body = body if isinstance(body, bytes) else body.encode()
                headers = {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", **headers}
                # Byte ranges, as on a real download server (Firefox's update
                # downloader fetches big files in chunks).
                m = re.match(r"bytes=(\d+)-(\d*)$", self.headers.get("Range", ""))
                if m:
                    start = int(m.group(1))
                    end = min(int(m.group(2) or len(body) - 1), len(body) - 1)
                    headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
                    body = body[start:end + 1]
                self.send_response(206 if m else 200)
                headers["Content-Length"] = str(len(body))
                headers["Accept-Ranges"] = "bytes"
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the browser stopped reading; fine for a test server

            def log_message(self, *a):
                pass

        class Dual(http.server.ThreadingHTTPServer):
            address_family = socket.AF_INET6

            def server_bind(self):
                # Answer on ::1 and 127.0.0.1 alike: "localhost" may resolve to either.
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                super().server_bind()

        self.httpd = Dual(("::", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, host, path):
        return f"http://{host}:{self.port}{path}"

    def page(self, path, html, headers=None):
        self.pages[path] = (html, headers or {})

    def close(self):
        self.httpd.shutdown()


class Browser:
    def __init__(self, app=None, extra_prefs=None, profile=None, env=None, headless=True, log=None):
        # profile=<dir> reuses one (and keeps it) to test a second launch.
        self.keep = profile is not None
        self.prof = profile or tempfile.mkdtemp(prefix="veil-test.")
        self.port = free_port()
        prefs = {
            "marionette.port": self.port,
            "dom.security.https_only_mode.upgrade_local": False,
            **(extra_prefs or {}),
        }
        with open(os.path.join(self.prof, "user.js"), "w") as f:
            for k, v in prefs.items():
                f.write(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n")
        env = dict(os.environ, **(env or {}))
        if headless:
            env["MOZ_HEADLESS"] = "1"
        self.proc = subprocess.Popen(
            [str(app or find_app()), "-no-remote", "-profile", self.prof,
             "-marionette", "-remote-allow-system-access"],
            env=env, stdout=open(log, "a") if log else subprocess.DEVNULL, stderr=subprocess.STDOUT if log else subprocess.DEVNULL)
        self.sock = self._connect()
        self._id = 0
        self._recv()  # handshake
        self._cmd("WebDriver:NewSession", {"capabilities": {}})

    def _connect(self):
        end = time.time() + 60
        while time.time() < end:
            try:
                return socket.create_connection(("127.0.0.1", self.port), timeout=120)
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("browser never opened its Marionette port")

    def _recv(self):
        n = b""
        while not n.endswith(b":"):
            n += self.sock.recv(1)
        size, data = int(n[:-1]), b""
        while len(data) < size:
            data += self.sock.recv(size - len(data))
        return json.loads(data)

    def _cmd(self, name, params=None):
        self._id += 1
        msg = json.dumps([0, self._id, name, params or {}]).encode()
        self.sock.sendall(str(len(msg)).encode() + b":" + msg)
        while True:
            r = self._recv()
            if r[0] == 1 and r[1] == self._id:
                if r[2]:
                    raise RuntimeError(f"{name}: {r[2].get('error')}: {r[2].get('message')}")
                return r[3]

    def go(self, url):
        """Navigate; returns the about: URL if the browser showed an error page."""
        try:
            self._cmd("WebDriver:Navigate", {"url": url})
        except RuntimeError as e:
            m = re.search(r"Reached error page: (\S+)", str(e))
            if not m:
                raise
            return m.group(1)

    def js(self, script, *args):
        return self._cmd("WebDriver:ExecuteScript", {"script": script, "args": list(args)})["value"]

    def chrome_js(self, script, *args, asynchronous=False):
        self._cmd("Marionette:SetContext", {"value": "chrome"})
        try:
            cmd = "WebDriver:ExecuteAsyncScript" if asynchronous else "WebDriver:ExecuteScript"
            return self._cmd(cmd, {"script": script, "args": list(args)})["value"]
        finally:
            self._cmd("Marionette:SetContext", {"value": "content"})

    def pref(self, name):
        return self.chrome_js("""
          const n = arguments[0], P = Services.prefs;
          switch (P.getPrefType(n)) {
            case P.PREF_BOOL: return P.getBoolPref(n);
            case P.PREF_INT: return P.getIntPref(n);
            case P.PREF_STRING: return P.getStringPref(n);
          }
          return null;""", name)

    def watch_network(self):
        """Start recording every URL that got a response from the NETWORK.
        A tracker that was blocked, or swapped for a local stand-in script
        (Firefox's SmartBlock shims, uBlock Origin's redirects), never shows
        up here, even though the page sees its <script> "load"."""
        self.chrome_js("""
          if (!window.veilSeen) {
            window.veilSeen = [];
            window.veilObs = { observe(s) { try {
              s.QueryInterface(Ci.nsIHttpChannel); window.veilSeen.push(s.URI.spec);
            } catch (e) {} } };
            Services.obs.addObserver(window.veilObs, "http-on-examine-response");
            Services.obs.addObserver(window.veilObs, "http-on-examine-cached-response");
          }
          window.veilSeen.length = 0;""")

    def network_seen(self):
        return self.chrome_js("return window.veilSeen.slice()")

    def wait(self, script, timeout=20, *args):
        end = time.time() + timeout
        while time.time() < end:
            v = self.js(script, *args)
            if v:
                return v
            time.sleep(0.25)
        return None

    def quit(self):
        """Quit the way a user does, so shutdown tasks (clear-on-exit) run."""
        with contextlib.suppress(Exception):
            self._cmd("Marionette:Quit", {"flags": ["eAttemptQuit"]})
        self.proc.wait(60)
        self.close()

    def crash(self):
        """No shutdown at all: what a crash or Force Quit leaves behind."""
        self.proc.kill()
        self.proc.wait(15)
        self.close()

    def close(self):
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self._cmd("Marionette:Quit", {"flags": ["eForceQuit"]})
        with contextlib.suppress(Exception):
            self.proc.wait(15)
        if self.proc.poll() is None:
            self.proc.kill()
        if not self.keep:
            shutil.rmtree(self.prof, ignore_errors=True)


class Results:
    """PASS/FAIL lines a beginner can read; exit code 1 if anything failed."""

    def __init__(self):
        self.failed = 0

    def check(self, name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
        self.failed += not ok

    def done(self):
        print(f"\n{'all passed' if not self.failed else f'{self.failed} FAILED'}")
        raise SystemExit(1 if self.failed else 0)
