#!/usr/bin/env python3
"""Layer Veil's changes onto a LibreWolf source tree that `make dir` made.

    python3 veil/apply.py librewolf-<version>-<release>

Idempotent: every run rebuilds lw/librewolf.cfg and lw/policies.json from
LibreWolf's originals in settings/ plus Veil's files, so it is safe to run
again on an existing tree after editing a pref (then `./mach build faster`).

Order matters in a .cfg: a later defaultPref/lockPref for the same name wins,
so Veil's prefs are appended AFTER LibreWolf's.
"""
import hashlib
import json
import pathlib
import shutil
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
VEIL = ROOT / "veil"


def merge(base, extra):
    """Deep-merge dicts; lists and scalars from `extra` replace `base`, and
    null removes the key."""
    out = dict(base)
    for k, v in extra.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def bundle_extensions(lw):
    """Fetch each pinned extension (cached in veil/.cache), check its sha256,
    and ship it in distribution/extensions so it is on before the first page."""
    spec = json.loads((VEIL / "extensions.json").read_text())["extensions"]
    cache = VEIL / ".cache"
    cache.mkdir(exist_ok=True)
    dest = lw / "extensions"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir()
    names = []
    for ext in spec:
        f = cache / f"{ext['id']}-{ext['version']}.xpi"
        if not f.exists():
            print(f"veil: downloading {ext['url']}")
            urllib.request.urlretrieve(ext["url"], f)
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if digest != ext["sha256"]:
            f.unlink()
            sys.exit(f"veil: CHECKSUM MISMATCH for {ext['id']}: got {digest}")
        shutil.copy(f, dest / f"{ext['id']}.xpi")
        names.append(f'    "extensions/{ext["id"]}.xpi",')

    build = lw / "moz.build"
    text = build.read_text().split(MARK)[0].rstrip() + "\n"
    text += f"\n{MARK}\nFINAL_TARGET_FILES.distribution.extensions += [\n" + "\n".join(names) + "\n]\n"
    build.write_text(text)


MARK = "# VEIL: bundled extensions (written by veil/apply.py)"


def enable_updater(tree, pol):
    """Firefox's own updater, trusting only Veil's keys and Veil's releases.
    LibreWolf ships it compiled out (mozconfig) and switched off (policies)."""
    rel = json.loads((VEIL / "release.json").read_text())
    mozconfig = tree / "mozconfig"
    lines = [l for l in mozconfig.read_text().splitlines()
             if l.strip() != "ac_add_options --disable-updater" and "MAR_CHANNEL_ID" not in l]
    lines += [f"ac_add_options MAR_CHANNEL_ID={rel['mar_channel']}  # VEIL",
              f"ac_add_options ACCEPTED_MAR_CHANNEL_IDS={rel['mar_channel']}  # VEIL"]
    mozconfig.write_text("\n".join(lines) + "\n")
    # The updater only applies a MAR signed by one of these (release channel).
    for der in ("release_primary.der", "release_secondary.der"):
        shutil.copy(VEIL / "keys" / der, tree / "toolkit/mozapps/update/updater" / der)
    pol["policies"].pop("DisableAppUpdate", None)
    pol["policies"]["AppUpdateURL"] = rel["releases"] + "/latest/download/update-%BUILD_TARGET%.xml"


def main(tree):
    lw = ROOT / tree / "lw"
    if not lw.is_dir():
        sys.exit(f"{lw} does not exist; run `make dir` first")

    cfg = (ROOT / "settings/librewolf.cfg").read_text()
    for f in sorted((VEIL / "prefs").glob("*.cfg")):
        cfg += f"\n\n/** ---- VEIL: {f.name} ---- */\n" + f.read_text()
    (lw / "librewolf.cfg").write_text(cfg)

    pol = json.loads((ROOT / "settings/distribution/policies.json").read_text())
    extra = VEIL / "policies.json"
    if extra.exists():
        pol["policies"] = merge(pol["policies"], json.loads(extra.read_text())["policies"])
    enable_updater(ROOT / tree, pol)
    (lw / "policies.json").write_text(json.dumps(pol, indent=4) + "\n")

    bundle_extensions(lw)
    print(f"veil: wrote {lw/'librewolf.cfg'} and {lw/'policies.json'}, updater enabled")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__))
