#!/usr/bin/env python3
"""What did an upstream update change in the browser's settings?

    python3 veil/tools/pref_diff.py <old librewolf.cfg> <new librewolf.cfg>

Compares the effective prefs (the last pref/defaultPref/lockPref of each
name wins, as in Firefox) and lists every pref that was added, removed or
changed. Prefs Veil sets itself, or that its tests check, are marked:
those are the ones to read closely, because a change there can quietly
undo a Veil protection or make a test meaningless.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STMT = re.compile(r'^\s*(defaultPref|pref|lockPref|clearPref)\(\s*"([^"]+)"\s*(?:,\s*(.+?))?\s*\)\s*;', re.M | re.S)


def effective(path):
    text = re.sub(r"/\*.*?\*/", "", pathlib.Path(path).read_text(), flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    prefs = {}
    for kind, name, value in STMT.findall(text):
        if kind == "clearPref":
            prefs.pop(name, None)
        else:
            prefs[name] = f"{' '.join(value.split())}" + ("  [locked]" if kind == "lockPref" else "")
    return prefs


def main(old, new):
    a, b = effective(old), effective(new)
    veil = set()
    for f in (ROOT / "veil/prefs").glob("*.cfg"):
        veil |= set(effective(f))
    tests = "".join(f.read_text() for f in (ROOT / "veil/tests").glob("*.py"))

    def mark(n):
        return " <- VEIL SETS THIS" if n in veil else (" <- A TEST CHECKS THIS" if n in tests else "")

    rows = [("+", n, b[n]) for n in sorted(b.keys() - a.keys())]
    rows += [("-", n, a[n]) for n in sorted(a.keys() - b.keys())]
    rows += [("~", n, f"{a[n]}  ->  {b[n]}") for n in sorted(a.keys() & b.keys()) if a[n] != b[n]]
    rows.sort(key=lambda r: (not mark(r[1]), r[1]))
    for sign, n, v in rows:
        print(f"{sign} {n} = {v}{mark(n)}")
    flagged = sum(1 for r in rows if mark(r[1]))
    print(f"\n{len(rows)} pref changes, {flagged} touching Veil's prefs or tests"
          f" (+ added, - removed, ~ changed)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
