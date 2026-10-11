#!/usr/bin/env python3
"""Layer Veil's changes onto a LibreWolf source tree that `make dir` made.

    python3 veil/apply.py librewolf-<version>-<release>

Idempotent: every run rebuilds lw/librewolf.cfg and lw/policies.json from
LibreWolf's originals in settings/ plus Veil's files, so it is safe to run
again on an existing tree after editing a pref (then `./mach build faster`).

Order matters in a .cfg: a later defaultPref/lockPref for the same name wins,
so Veil's prefs are appended AFTER LibreWolf's.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VEIL = ROOT / "veil"


def merge(base, extra):
    """Deep-merge dicts; lists and scalars from `extra` replace `base`."""
    out = dict(base)
    for k, v in extra.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


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
    (lw / "policies.json").write_text(json.dumps(pol, indent=4) + "\n")

    print(f"veil: wrote {lw/'librewolf.cfg'} and {lw/'policies.json'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__))
