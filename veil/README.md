# Veil

Veil is LibreWolf with a small set of changes on top. Everything Veil adds
lives in this `veil/` folder, plus one line in the top-level `Makefile`
(`python3 veil/apply.py ...` in the source-tree recipe). Rebasing onto a new
LibreWolf release means: pull upstream, keep that one Makefile line, rebuild,
rerun the tests below.

| path | what |
|---|---|
| `prefs/*.cfg` | Veil's prefs, appended after LibreWolf's `librewolf.cfg` (later wins) |
| `policies.json` | optional; deep-merged into LibreWolf's `policies.json` |
| `extensions.json` | extensions bundled into the build, pinned by version + sha256 |
| `apply.py` | writes all of the above into the source tree (`lw/`) |
| `tools/` | network audit (mitmproxy) and packet capture |
| `tests/` | checks against the running browser |
| `captures/` | audit results, committed as evidence |

## Everyday commands

```sh
cd ~/src/veil-source && source env.sh

# after editing prefs/*.cfg (seconds)
python3 veil/apply.py librewolf-157.0.1-1 && (cd librewolf-157.0.1-1 && ./mach build faster)
# after editing extensions.json (needs the full incremental build, ~30 s)
python3 veil/apply.py librewolf-157.0.1-1 && (cd librewolf-157.0.1-1 && ./mach build)

python3 veil/tests/test_tracking.py        # phase 3 checks, headless, ~1 min
python3 veil/tests/test_isolation.py       # phase 4 checks, ~1 min
python3 veil/tests/test_fingerprint.py     # phase 5 uniformity checks, ~1 min
python3 veil/tests/test_network.py         # phase 6: HTTPS-only, DoH, ECH, WebRTC, ~1 min
python3 veil/tests/fp_collect.py           # full fingerprint table, RFP on vs off
python3 veil/tests/cover_your_tracks.py --compare   # EFF test, opens a window
python3 veil/tests/probe_startup.py        # first-launch blocking gap
veil/tools/audit.sh <tag>                  # network audit, ~11 min
python3 veil/tools/compare.py baseline <tag>
sudo veil/tools/pcap.sh                    # packet-level check, no proxy
```

`veil/tools/setup-mitm.sh` installs mitmproxy once, into `.venv-mitm`.
