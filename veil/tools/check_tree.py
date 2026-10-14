#!/usr/bin/env python3
"""Does everything Veil configures still exist in this Firefox?

    python3 veil/tools/check_tree.py librewolf-<version>-<release>

Run after every upstream update, before building. Firefox renames and
removes prefs between versions, and a pref that no longer exists is set
without any error, so it just silently stops protecting you. This checks:

  - every pref named in veil/prefs/*.cfg appears in the Firefox source
    (its pref lists, or any code that reads it by name);
  - every policy in the final policies.json is one this Firefox knows, and
    has the right basic type;
  - the build config, signing keys and update address Veil's updater needs.

Exit code 1 if anything is missing. Takes about a minute (one source scan).
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
VEIL = ROOT / "veil"
PREF = re.compile(r'^\s*(?:defaultPref|pref|lockPref|clearPref)\(\s*"([^"]+)"', re.M)
SOURCES = ["*.yaml", "*.js", "*.mjs", "*.cpp", "*.h", "*.rs", "*.py", "*.json", "*.idl", "*.toml"]
TYPES = {"boolean": bool, "string": str, "object": dict, "array": list, "number": (int, float), "integer": int}


def main(tree):
    tree = ROOT / tree
    problems = []

    # ---- prefs: one fixed-string scan of the source for all names at once
    names = {}
    for f in sorted((VEIL / "prefs").glob("*.cfg")):
        for n in PREF.findall(f.read_text()):
            names.setdefault(n, f.name)
    listed = (tree / "modules/libpref/init/StaticPrefList.yaml").read_text()
    js = "".join((tree / p).read_text() for p in ["modules/libpref/init/all.js", "browser/app/profile/firefox.js"])
    pattern = "\n".join(f'"{n}"' for n in names)
    seen = subprocess.run(
        ["grep", "-rhoF", "-e", pattern, *[f"--include={g}" for g in SOURCES],
         "--exclude-dir=obj-*", "--exclude-dir=lw", "--exclude-dir=testing", "--exclude-dir=test", "--exclude-dir=tests", "."],
        cwd=tree, capture_output=True, text=True).stdout
    seen = {s.strip('"') for s in seen.split()}
    for n, f in names.items():
        if f"- name: {n}\n" in listed or f'"{n}"' in js:
            where = "pref list"
        elif n in seen:
            where = "read by code"
        else:
            where = None
            problems.append(f"pref {n} ({f}) is not in this Firefox: removed or renamed?")
        print(f"{'ok  ' if where else 'GONE'}  {n:60} {where or ''}")

    # ---- policies, against this Firefox's own schema
    schema = json.loads((tree / "browser/components/enterprisepolicies/schemas/policies-schema.json").read_text())["properties"]
    final = json.loads((tree / "lw/policies.json").read_text())["policies"]
    ours = json.loads((VEIL / "policies.json").read_text())["policies"]
    for name, value in final.items():
        spec = schema.get(name)
        if spec is None:
            problems.append(f"policy {name} is unknown to this Firefox")
        elif "type" in spec and not isinstance(value, TYPES.get(spec["type"], object)):
            problems.append(f"policy {name} should be a {spec['type']}")
    print(f"ok    {len(final)} policies checked ({len(ours)} set by Veil)")

    # ---- updater: build config, keys, address
    mozconfig = (tree / "mozconfig").read_text()
    if "--disable-updater" in mozconfig:
        problems.append("mozconfig still has --disable-updater")
    if "--enable-update-channel=release" not in mozconfig:
        problems.append("update channel is not release: the build would trust Mozilla's dep certificates, not Veil's")
    keys = VEIL / "keys"
    for der in ["release_primary.der", "release_secondary.der"]:
        built = tree / "toolkit/mozapps/update/updater" / der
        if not (keys / der).exists():
            problems.append(f"veil/keys/{der} is missing: run veil/tools/make_keys.sh")
        elif built.read_bytes() != (keys / der).read_bytes():
            problems.append(f"{der} in the tree is not Veil's key")
    # After a build: the certificates actually compiled into the updater.
    for header, der in [("primaryCert.h", "release_primary.der"), ("secondaryCert.h", "release_secondary.der")]:
        for h in tree.glob(f"obj-*/toolkit/mozapps/update/updater/{header}"):
            compiled = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", h.read_text()))
            if compiled != (keys / der).read_bytes():
                problems.append(f"the built updater in {tree.name} trusts a key that is not veil/keys/{der}: rebuild")
            else:
                print(f"ok    built updater trusts veil/keys/{der}")
    url = final.get("AppUpdateURL", "")
    if final.get("DisableAppUpdate") or not url.startswith("https://") or "localhost" in url:
        problems.append(f"updates are off or point nowhere (AppUpdateURL={url!r})")

    print()
    for p in problems:
        print("PROBLEM", p)
    print("tree OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
