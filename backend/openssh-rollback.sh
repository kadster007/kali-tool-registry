#!/usr/bin/env bash
# Roll back the changes made by openssh-setup.sh.
# Stops the service and restores the timestamped sshd_config backup.
#
# Run:  sudo bash ~/openssh-rollback.sh

set -euo pipefail

CFG=/etc/ssh/sshd_config
MARKER=/etc/ssh/.last-backup

if [[ ! -f "$MARKER" ]]; then
    echo "ERROR: no /etc/ssh/.last-backup marker found."
    echo "       List backups manually:  ls -la /etc/ssh/sshd_config.bak.*"
    echo "       Then:  cp /etc/ssh/sshd_config.bak.<STAMP> /etc/ssh/sshd_config"
    exit 1
fi

BACKUP=$(cat "$MARKER")
if [[ ! -f "$BACKUP" ]]; then
    echo "ERROR: marker points to '$BACKUP' which doesn't exist."
    exit 2
fi

echo "==> Stopping and disabling ssh.service"
systemctl disable --now ssh.service 2>/dev/null || true

echo "==> Restoring sshd_config from $BACKUP"
cp -p "$BACKUP" "$CFG"

echo "==> Removing rollback marker (preserving the backup file itself)"
rm -f "$MARKER"

echo "==> Final state:"
echo "    ssh.service: $(systemctl is-active ssh.service 2>&1) / $(systemctl is-enabled ssh.service 2>&1)"
ss -tlnp 2>/dev/null | grep -E ':22|:2222' | sed 's/^/    /' || echo "    (no SSH listening — good if you wanted full rollback)"

echo
echo "Rollback complete. Tailscale's built-in SSH on port 22 is unaffected."
