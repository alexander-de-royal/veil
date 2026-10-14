# Veil

Veil is LibreWolf with a small set of changes on top. Everything Veil adds
lives in this `veil/` folder, plus one line in the top-level `Makefile`
(`python3 veil/apply.py ...` in the source-tree recipe), plus CI workflows in
`.github/workflows/veil-*.yml`.

| path | what |
|---|---|
| `prefs/*.cfg` | Veil's prefs, appended after LibreWolf's `librewolf.cfg` (later wins) |
| `policies.json` | optional; deep-merged into LibreWolf's `policies.json` |
| `extensions.json` | extensions bundled into the build, pinned by version + sha256 |
| `release.json` | where releases live (update address) and the update channel |
| `keys/` | Veil's two PUBLIC update-signing certificates, built into every copy |
| `apply.py` | writes all of the above into the source tree, turns the updater on |
| `tools/` | rebase, release, tree checks, network audit, packet capture |
| `ci/checks.sh` | the fast checks CI runs on every push (no compiling) |
| `tests/` | checks against the running browser |
| `captures/` | audit results, committed as evidence |

## Everyday commands

```sh
cd ~/src/veil-source && source env.sh
T=librewolf-$(cat version)-$(cat release)   # the current tree, e.g. librewolf-158.0-1

# after editing prefs/*.cfg (seconds)
python3 veil/apply.py $T && (cd $T && ./mach build faster)
# after editing extensions.json or release.json (~30 s)
python3 veil/apply.py $T && (cd $T && ./mach build)
python3 veil/tools/check_tree.py $T          # everything Veil sets exists; updater trusts veil/keys

python3 veil/tests/run_all.py              # every suite below, ~8 min
python3 veil/tests/test_tracking.py        # phase 3 checks, headless, ~1 min
python3 veil/tests/test_isolation.py       # phase 4 checks, ~1 min
python3 veil/tests/test_fingerprint.py     # phase 5 uniformity checks, ~1 min
python3 veil/tests/test_network.py         # phase 6: HTTPS-only, DoH, ECH, WebRTC, ~1 min
python3 veil/tests/test_update.py          # phase 7: old release updates to new, bad signature refused
python3 veil/tests/fp_collect.py           # full fingerprint table, RFP on vs off
python3 veil/tests/cover_your_tracks.py --compare   # EFF test, opens a window
python3 veil/tests/probe_startup.py        # first-launch blocking gap
veil/tools/audit.sh <tag>                  # network audit, ~11 min
python3 veil/tools/compare.py baseline <tag>
sudo veil/tools/pcap.sh                    # packet-level check, no proxy
```

`veil/tools/setup-mitm.sh` installs mitmproxy once, into `.venv-mitm`.

## A new LibreWolf release (fast rebase)

```sh
veil/tools/rebase.sh            # rebase, build tree, check, diff settings, build, test
veil/tools/rebase.sh --no-build # stop after the checks (~10 min)
```

It stops at the first problem and says what to do. The things to read in its
output: `PROBLEM` lines from `check_tree.py` (a Veil pref Firefox removed or
renamed), and the settings diff, where anything marked `VEIL SETS THIS` or
`A TEST CHECKS THIS` deserves a look. On GitHub, the weekly "Veil upstream
watch" workflow does the same without building and opens a pull request.

## Releasing

Once ever: `veil/tools/make_keys.sh`, then back up `~/.veil-signing`. It
holds the private keys every installed copy trusts. Lose them and no copy can
auto-update again; leak them and someone else can push updates to everyone.

Each release, after `rebase.sh` passed:

```sh
python3 veil/tools/release.py package librewolf-<version>-<release>   # this Mac's build
gh run download <run-id> -D veil/dist/<version>-<release>            # optional: CI's Linux builds
python3 veil/tools/release.py sign veil/dist/<version>-<release>     # sign + verify, locally
python3 veil/tests/test_update.py                                    # previous release updates to this one
python3 veil/tools/release.py sign veil/dist/<version>-<release> --publish
```

Installed copies check `<releases>/latest/download/update-<target>.xml`
every 4 hours (address in `release.json`), download the MAR, and apply it on
the next restart only if it is signed by one of the keys in `keys/`.
