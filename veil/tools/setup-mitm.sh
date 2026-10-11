#!/usr/bin/env bash
# One-time: install mitmproxy into .venv-mitm (the Homebrew cask installs empty
# on some machines, and a venv keeps it away from the build's Python).
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
python3 -m venv "$root/.venv-mitm"
"$root/.venv-mitm/bin/pip" install -q mitmproxy
"$root/.venv-mitm/bin/mitmdump" --version | head -1
