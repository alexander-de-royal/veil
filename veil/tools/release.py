#!/usr/bin/env python3
"""Turn a built tree into a signed Veil release, in two steps.

    python3 veil/tools/release.py package librewolf-<version>-<release>
    python3 veil/tools/release.py sign veil/dist/<version>-<release> [--publish]

`package` (any machine, CI included) writes veil/dist/<version>-<release>/:
  the installer/archive         what new users download (`mach package`)
  veil-<ver>-<target>.unsigned.mar  the update, not yet signed
  <target>.json                 version, build ID, update targets

`sign` (only where ~/.veil-signing is: your Mac; the key never goes to CI)
signs every unsigned MAR in the folder, checks the signature against the
committed veil/keys exactly as installed builds will, and writes
update-<target>.xml (what installed copies check every 4 hours) and
SHA256SUMS. A MAR that shipped builds would refuse is never written out.
Builds from CI: `gh run download <run-id> -D veil/dist/<version>-<release>`
into the same folder, then sign once for all platforms.

--publish uploads the folder as a GitHub release (gh CLI) to the repo in
veil/release.json. Without it nothing leaves this machine.
"""
import configparser
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from xml.sax.saxutils import quoteattr

ROOT = pathlib.Path(__file__).resolve().parents[2]
REL = json.loads((ROOT / "veil/release.json").read_text())
KEYS = pathlib.Path.home() / ".veil-signing/nssdb"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def targets(obj):
    """%BUILD_TARGET% values (Firefox's OS_XPCOMABI) this build serves."""
    info = json.loads((obj / "mozinfo.json").read_text())
    os_, cpu = info["os"], info["processor"]
    if os_ == "mac":
        # A universal build runs natively on both, so it asks under both names.
        return ["Darwin_aarch64-gcc3", "Darwin_x86_64-gcc3"] if info.get("universal") or cpu == "universal" \
            else [f"Darwin_{cpu}-gcc3"]
    if os_ == "linux":
        return [f"Linux_{cpu}-gcc3"]
    if os_ == "win":
        # Firefox appends the CPU it is running on (x64 builds on ARM report -aarch64).
        return [f"WINNT_{cpu}-msvc-{'x64' if cpu == 'x86_64' else cpu}"]
    sys.exit(f"unknown platform {os_}/{cpu}")


def staged_app(obj):
    """The packaged (not symlinked dev) application directory."""
    stage = obj / "dist/librewolf"
    apps = list(stage.glob("*.app"))
    return apps[0] if apps else stage


def build_id(app, version, ini_id):
    """The build ID the browser reports and the updater compares. It is
    compiled into the executable; `mach package` rewrites application.ini
    with a fresh timestamp the browser never reads, so don't trust that."""
    for exe in [*app.glob("Contents/MacOS/librewolf"), *app.glob("librewolf"), *app.glob("librewolf.exe")]:
        found = re.findall(re.escape(version.encode()) + rb"\x00+(\d{14})\x00", exe.read_bytes())
        if found:
            return found[0].decode()
    print(f"warning: no build ID in the executable, using application.ini's {ini_id}")
    return ini_id


def package(tree):
    tree = ROOT / tree
    obj = next(tree.glob("obj-*"))
    run(["./mach", "package"], cwd=tree)
    app = staged_app(obj)
    ini = configparser.ConfigParser()
    ini.read([*app.rglob("application.ini")][:1])
    name = tree.name.removeprefix("librewolf-")  # e.g. 158.0-1
    tgts = targets(obj)
    version = ini["App"]["Version"]
    meta = {"name": name, "version": version, "build_id": build_id(app, version, ini["App"]["BuildID"]), "targets": tgts}
    out = ROOT / "veil/dist" / name
    out.mkdir(parents=True, exist_ok=True)
    mar = out / f"veil-{name}-{tgts[0]}.unsigned.mar"
    run([tree / "tools/update-packaging/make_full_update.sh", mar, app], env={
        **os.environ, "MAR": str(obj / "dist/host/bin/mar"), "MOZ_PRODUCT_VERSION": meta["version"],
        "MAR_CHANNEL_ID": REL["mar_channel"]})
    for pkg in obj.glob(f"dist/librewolf-{name}*"):
        if pkg.is_file() and pkg.suffix in (".dmg", ".xz", ".bz2", ".zip", ".exe") and "_artifacts" not in pkg.name:
            shutil.copy(pkg, out)
    (out / f"{tgts[0]}.json").write_text(json.dumps({**meta, "mar": mar.name.replace(".unsigned", "")}, indent=2))
    print(f"\npackaged {name} (Firefox {meta['version']}, build {meta['build_id']}) for {', '.join(tgts)} in {out}")


def sign(out, publish=False):
    out = pathlib.Path(out).resolve()
    bins = next(d for d in ROOT.glob("librewolf-*/obj-*/dist/bin") if (d / "signmar").exists())  # signmar from any local build signs any platform's MAR
    env = dict(os.environ, DYLD_LIBRARY_PATH=str(bins), LD_LIBRARY_PATH=str(bins))
    # `gh run download` puts each platform in its own subfolder: flatten.
    for f in [f for f in out.rglob("*") if f.is_file() and f.parent != out]:
        f.rename(out / f.name)
    for d in sorted((d for d in out.rglob("*") if d.is_dir()), reverse=True):
        d.rmdir()
    metas = [json.loads(f.read_text()) for f in sorted(out.glob("*.json"))]
    if not metas:
        sys.exit(f"nothing to sign in {out}: run `release.py package` first")
    for meta in metas:
        mar, unsigned = out / meta["mar"], out / meta["mar"].replace(".mar", ".unsigned.mar")
        if unsigned.exists():
            run([bins / "signmar", "-d", KEYS, "-n", "veil-primary", "-s", unsigned, mar], env=env)
            # The same check installed builds make, against the committed public key.
            run([bins / "signmar", "-D", ROOT / "veil/keys/release_primary.der", "-v", mar], env=env)
            unsigned.unlink()
        data = mar.read_bytes()
        url = f"{REL['releases']}/download/v{meta['name']}/{mar.name}"
        for t in meta["targets"]:
            (out / f"update-{t}.xml").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<updates>\n'
                f'  <update type="minor" displayVersion={quoteattr(meta["name"])} appVersion={quoteattr(meta["version"])}'
                f' platformVersion={quoteattr(meta["version"])} buildID={quoteattr(meta["build_id"])}'
                f' detailsURL={quoteattr(REL["releases"] + "/tag/v" + meta["name"])}>\n'
                f'    <patch type="complete" URL={quoteattr(url)} size="{len(data)}"'
                f' hashFunction="sha512" hashValue="{hashlib.sha512(data).hexdigest()}"/>\n'
                '  </update>\n</updates>\n')
    files = sorted(f for f in out.iterdir() if f.name != "SHA256SUMS" and f.suffix != ".json")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in files))
    for f in sorted(out.iterdir()):
        print(f"  {f.stat().st_size / 1e6:8.1f} MB  {f.name}")

    if publish:
        name = metas[0]["name"]
        repo = REL["releases"].removeprefix("https://github.com/").removesuffix("/releases")
        upload = [str(f) for f in files] + [str(out / "SHA256SUMS")]
        if subprocess.run(["gh", "release", "view", f"v{name}", "-R", repo], capture_output=True).returncode:
            run(["gh", "release", "create", f"v{name}", "-R", repo, "--title", f"Veil {name}",
                 "--notes", f"Based on LibreWolf {name} (Firefox {metas[0]['version']}).", *upload])
        else:
            run(["gh", "release", "upload", f"v{name}", "-R", repo, "--clobber", *upload])


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--publish"]
    if len(args) != 2 or args[0] not in ("package", "sign"):
        sys.exit(__doc__)
    package(args[1]) if args[0] == "package" else sign(args[1], publish="--publish" in sys.argv)
