#!/usr/bin/env python3
"""Run every Veil test suite against the current build.

    python3 veil/tests/run_all.py            all suites, ~6 min, needs internet
    python3 veil/tests/run_all.py network    only suites whose name matches

Each suite runs in its own process (fresh browser, fresh profiles). Prints
each suite's failures and a summary; exit code 1 if any suite failed.
"""
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SUITES = ["test_tracking", "test_isolation", "test_fingerprint", "test_network", "test_update"]

only = sys.argv[1:]
results = []
for name in SUITES:
    if only and not any(o in name for o in only):
        continue
    if not (HERE / f"{name}.py").exists():
        continue
    print(f"== {name}", flush=True)
    t = time.time()
    p = subprocess.run([sys.executable, str(HERE / f"{name}.py")], cwd=HERE, capture_output=True, text=True)
    out = p.stdout + p.stderr
    for line in out.splitlines():
        if line.startswith("FAIL") or "Traceback" in line or "Error" in line:
            print("   ", line, flush=True)
    results.append((name, p.returncode == 0, time.time() - t))
    print(f"   {'passed' if p.returncode == 0 else 'FAILED'} in {time.time() - t:.0f}s", flush=True)

print()
for name, ok, secs in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:20} {secs:4.0f}s")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{'all suites passed' if not failed else f'{failed} suite(s) FAILED'}")
sys.exit(1 if failed else 0)
