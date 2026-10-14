"""Phase 7: an installed Veil really updates itself, and only from Veil.

    python3 veil/tests/test_update.py [old-release-dir new-release-dir]

Default: the two newest releases in veil/dist (made by veil/tools/release.py).
Skips (passes) if there are fewer than two. Nothing goes to the internet: a
local server stands in for GitHub, and the installed copy's update address
is pointed at it.

  1. install the old release in a temp folder, let it check for updates,
     download, verify and stage the new one; restart: it is the new version;
  2. same, but the update is signed with some other key (what an attacker
     who took over the download server could do): it must be refused, and
     the old version keeps running.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from harness import ROOT, Browser, Results, Server

DIST = ROOT / "veil/dist"
r = Results()


def version_key(d):
    return [int(x) for x in re.findall(r"\d+", d.name)]


releases = sorted((d for d in DIST.glob("*") if list(d.glob("*.mar"))), key=version_key)
if len(sys.argv) == 3:
    old, new = map(pathlib.Path, sys.argv[1:])
elif len(releases) >= 2:
    old, new = releases[-2], releases[-1]
else:
    print("skipped: needs two releases in veil/dist (veil/tools/release.py)")
    r.done()
print(f"updating {old.name} -> {new.name}")


def install(release, where):
    """Unpack a release the way a user would, return the app's executable."""
    dmg = next(release.glob("*.dmg"), None)
    if dmg:
        mnt = tempfile.mkdtemp()
        subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-readonly", "-mountpoint", mnt, dmg], check=True)
        try:
            app = next(pathlib.Path(mnt).glob("*.app"))
            subprocess.run(["cp", "-R", app, where], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", mnt], check=True)
        app = next(pathlib.Path(where).glob("*.app"))
        return app / "Contents/MacOS/librewolf", app / "Contents/Resources"
    tar = next(release.glob("*.tar.*"))
    subprocess.run(["tar", "xf", tar, "-C", where], check=True)
    top = next(p for p in pathlib.Path(where).iterdir() if p.is_dir())
    return top / "librewolf", top


def point_at(resources, url):
    pol = resources / "distribution/policies.json"
    data = json.loads(pol.read_text())
    data["policies"]["AppUpdateURL"] = url
    pol.write_text(json.dumps(data, indent=4))


def resign_with_stranger_key(mar, out, tmp):
    """The new release's MAR with its signature replaced by a key Veil never trusted."""
    bins = next(d for d in ROOT.glob("librewolf-*/obj-*/dist/bin") if (d / "signmar").exists())
    env = dict(os.environ, DYLD_LIBRARY_PATH=str(bins), LD_LIBRARY_PATH=str(bins))
    db = f"sql:{tmp}/stranger"
    os.makedirs(f"{tmp}/stranger")
    pathlib.Path(f"{tmp}/noise").write_bytes(os.urandom(2048))
    run = lambda *c: subprocess.run([str(bins / c[0]), *map(str, c[1:])], env=env, check=True, capture_output=True)
    run("certutil", "-N", "-d", db, "--empty-password")
    run("certutil", "-S", "-d", db, "-n", "stranger", "-s", "CN=Not Veil", "-x", "-t", ",,",
        "-k", "rsa", "-g", "4096", "-Z", "SHA384", "-z", f"{tmp}/noise")
    run("signmar", "-r", mar, f"{tmp}/stripped.mar")
    run("signmar", "-d", db, "-n", "stranger", "-s", f"{tmp}/stripped.mar", out)


CHECK = """
  const done = arguments[arguments.length - 1];
  const { AppUpdater } = ChromeUtils.importESModule("resource://gre/modules/AppUpdater.sys.mjs");
  const au = new AppUpdater(), seen = [];
  const names = Object.fromEntries(Object.entries(AppUpdater.STATUS).map(([k, v]) => [v, k]));
  au.addListener(status => {
    seen.push(names[status]);
    if (!["CHECKING", "DOWNLOADING", "DOWNLOAD_AND_INSTALL", "STAGING", "NEVER_CHECKED"].includes(names[status]))
      done(seen);
  });
  au.check();
"""
STATE = """
  const done = arguments[arguments.length - 1];
  const um = Cc["@mozilla.org/updates/update-manager;1"].getService(Ci.nsIUpdateManager);
  um.getHistory().then(h => done({version: Services.appinfo.version, build: Services.appinfo.appBuildID,
    history: h.map(u => [u.appVersion, u.state, u.statusText, u.errorCode])}));
"""


def attempt(label, mar_bytes):
    """Install old, offer it `mar_bytes` as the update; returns (before, after-restart)."""
    tmp = tempfile.mkdtemp(prefix="veil-update.")
    srv = Server()
    exe, resources = install(old, tmp)
    xml = next(new.glob("update-*.xml")).read_text()
    xml = re.sub(r'(<patch [^>]*?)URL="[^"]+"', lambda m: m.group(1) + f'URL="{srv.url("127.0.0.1", "/update.mar")}"', xml)
    xml = re.sub(r'size="\d+"', f'size="{len(mar_bytes)}"', xml)
    xml = re.sub(r' hashFunction="[^"]+" hashValue="[^"]+"', "", xml)  # signature is what counts
    srv.page("/update.xml", xml, {"Content-Type": "text/xml"})
    srv.page("/update.mar", mar_bytes, {"Content-Type": "application/octet-stream"})
    point_at(resources, srv.url("127.0.0.1", "/update.xml"))

    prof = tempfile.mkdtemp(prefix="veil-update-prof.")
    prefs = {"app.update.disabledForTesting": False,  # Marionette turns updates off otherwise
             "app.update.log": True}
    log = os.environ.get("VEIL_UPDATE_LOG")
    b = Browser(app=exe, profile=prof, extra_prefs=prefs, log=log)
    b._cmd("WebDriver:SetTimeouts", {"script": 600000})
    if log:  # LibreWolf's cfg turns console output off on every start
        b.chrome_js('Services.prefs.setBoolPref("devtools.console.stdout.chrome", true)')
    before = b.chrome_js(STATE, asynchronous=True)
    seen = b.chrome_js(CHECK, asynchronous=True)
    steps = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    print(f"info  {label}: updater went {' -> '.join(steps)}", flush=True)
    b.quit()
    b = Browser(app=exe, profile=prof, extra_prefs=prefs, log=log)  # the update applies on this start
    after = b.chrome_js(STATE, asynchronous=True)
    b.close()
    hits = [p for _, p in srv.hits]
    srv.close()
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(prof, ignore_errors=True)
    return before, after, seen, hits


mar = next(new.glob("*.mar")).read_bytes()
before, after, seen, hits = attempt("Veil-signed update", mar)
r.check("checks the update address and downloads the update",
        any(h.startswith("/update.xml") for h in hits) and "/update.mar" in hits, str(hits))
r.check("the update is verified and ready on restart", seen[-1] == "READY_FOR_RESTART",
        f"{seen[-1]}; history: {after['history']}")
r.check(f"after restart it runs the new version ({before['version']} -> {after['version']})",
        after["build"] != before["build"] and after["version"] >= before["version"],
        f"build {before['build']} -> {after['build']}")

tmp = tempfile.mkdtemp()
resign_with_stranger_key(next(new.glob("*.mar")), f"{tmp}/evil.mar", tmp)
before, after, seen, hits = attempt("update signed by another key", pathlib.Path(f"{tmp}/evil.mar").read_bytes())
shutil.rmtree(tmp, ignore_errors=True)
r.check("an update signed by another key is refused", after["build"] == before["build"],
        f"still build {after['build']}; history: {after['history']}")
r.done()
