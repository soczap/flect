#!/usr/bin/env bash
# One-time privileged setup for Flect. Run as:  sudo ~/flect/deploy/root/install-root.sh
# Installs: the nftables table + boot unit, the validated flect-nft helper, a one-line sudoers rule,
# and an AppArmor profile that lets a dedicated bwrap copy create namespaces for the test sandbox.
# It does NOT change the global userns sysctl, open ports, or grant any other privilege.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLECT_USER="${FLECT_USER:-${SUDO_USER:-enterprise}}"

echo "==> nftables table"
install -d -m 0755 /etc/flect
install -m 0644 "$HERE/flect.nft" /etc/flect/flect.nft
[[ -f /etc/flect/allowlist ]] || printf '# extra CIDRs that must never be blocked, one per line\n' > /etc/flect/allowlist
nft -c -f /etc/flect/flect.nft
install -m 0644 "$HERE/flect-nft.service" /etc/systemd/system/flect-nft.service
systemctl daemon-reload
systemctl enable --now flect-nft.service

echo "==> flect-nft helper + sudoers"
install -o root -g root -m 0755 "$HERE/flect-nft" /usr/local/sbin/flect-nft
sed "s/^enterprise /${FLECT_USER} /" "$HERE/sudoers.flect" > /tmp/flect.sudoers.$$
visudo -cf /tmp/flect.sudoers.$$
install -o root -g root -m 0440 /tmp/flect.sudoers.$$ /etc/sudoers.d/flect
rm -f /tmp/flect.sudoers.$$

echo "==> sandbox: dedicated bwrap + AppArmor userns profile"
install -d -m 0755 /usr/local/lib/flect
install -o root -g "$FLECT_USER" -m 0750 /usr/bin/bwrap /usr/local/lib/flect/bwrap
install -m 0644 "$HERE/apparmor-flect-bwrap" /etc/apparmor.d/flect-bwrap
apparmor_parser -r /etc/apparmor.d/flect-bwrap

echo "==> verify"
sudo -u "$FLECT_USER" sudo -n /usr/local/sbin/flect-nft list >/dev/null && echo "flect-nft: ok"
sudo -u "$FLECT_USER" /usr/local/lib/flect/bwrap --unshare-all --ro-bind / / --proc /proc --dev /dev true \
  && echo "sandbox: ok"
echo "Done. Flect will report 'nft: ok' and 'sandbox: ok' within 30 seconds."
