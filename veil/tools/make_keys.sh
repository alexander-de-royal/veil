#!/bin/bash
# Create Veil's update-signing keys. Run ONCE, ever.
#
#   veil/tools/make_keys.sh
#
# Every Veil build carries the two PUBLIC certificates (veil/keys/*.der,
# committed) and refuses any update not signed by one of the two private keys.
# The private keys stay in ~/.veil-signing, outside the repo, never in CI.
#
#   primary    signs every release
#   secondary  a spare: if the primary is lost or leaks, sign with the
#              secondary and ship a build that swaps in a new primary.
#
# LOSE BOTH and no installed Veil can ever auto-update again: everyone has to
# download a new build by hand. Back the folder up (see the end of this file).
set -euo pipefail
cd "$(dirname "$0")/../.."
KEYS=~/.veil-signing
DB="sql:$KEYS/nssdb"
certutil=$(ls -d librewolf-*/obj-*/dist/bin/certutil | tail -1)
export DYLD_LIBRARY_PATH=$(dirname "$certutil") LD_LIBRARY_PATH=$(dirname "$certutil")

if [ -e "$KEYS/nssdb" ]; then
  echo "$KEYS/nssdb already exists: keys were made before. Not touching them." >&2
  exit 1
fi
mkdir -p "$KEYS/nssdb" veil/keys
chmod 700 "$KEYS"
# No password, so release signing can run unattended; the folder is only
# readable by you, and FileVault encrypts it on disk.
"$certutil" -N -d "$DB" --empty-password
for which in primary secondary; do
  # RSA 4096 + SHA-384: what Firefox's updater verifies.
  head -c 4096 /dev/urandom > "$KEYS/noise"
  "$certutil" -S -d "$DB" -n "veil-$which" -s "CN=Veil update signing ($which)" \
    -x -t ",," -k rsa -g 4096 -Z SHA384 -v 240 -z "$KEYS/noise"
  "$certutil" -L -d "$DB" -n "veil-$which" -r > "veil/keys/release_$which.der"
done
rm -f "$KEYS/noise"
echo
echo "Private keys: $KEYS/nssdb   (back this up, keep it secret)"
echo "Public certs: veil/keys/release_primary.der, release_secondary.der (commit these)"
shasum -a 256 veil/keys/*.der

# Backup, e.g. to a USB stick or a password manager attachment: a
# password-protected copy of both keys:
#   pk12util -o veil-keys.p12 -n veil-primary -d sql:~/.veil-signing/nssdb
#   pk12util -o veil-keys2.p12 -n veil-secondary -d sql:~/.veil-signing/nssdb
