#!/usr/bin/env bash
# Add LAN-IP listener to OpenSSH on kadx so the phone can reach :2222 via 192.168.1.165
# when Tailscale is being flaky. Tailscale listener is preserved.
#
# Run: sudo bash ~/openssh-add-lan.sh
# Undo: sudo bash ~/openssh-rollback.sh
set -euo pipefail

CFG=/etc/ssh/sshd_config
LAN_IP=$(ip -4 addr show eth0 | awk '/inet /{print $2}' | cut -d/ -f1)
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="${CFG}.bak.${STAMP}"

if [[ -z "$LAN_IP" ]]; then
    echo "ERROR: couldn't determine kadx's eth0 LAN IP"
    exit 1
fi
echo "==> kadx LAN IP detected: $LAN_IP"

echo "==> Backing up $CFG -> $BACKUP"
cp -p "$CFG" "$BACKUP"
echo "$BACKUP" > /etc/ssh/.last-backup

# Add LAN ListenAddress only if it's not already there.
if grep -qE "^\s*ListenAddress\s+${LAN_IP}\s*$" "$CFG"; then
    echo "==> LAN ListenAddress already present, nothing to do."
else
    echo "==> Inserting ListenAddress $LAN_IP"
    # Insert after the first existing ListenAddress line so all listeners are grouped.
    if grep -qE "^\s*ListenAddress\s+" "$CFG"; then
        sed -i "0,/^[[:space:]]*ListenAddress/s//ListenAddress ${LAN_IP}\n&/" "$CFG"
    else
        printf "\nListenAddress %s\n" "$LAN_IP" >> "$CFG"
    fi
fi

# Also clean up any stale ListenAddress lines pointing to non-existent IPs (e.g. phone IP).
ALL_IPS=$(ip -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -E '^[0-9a-fA-F:.]+$' | sort -u)
while read -r addr; do
    [[ -z "$addr" ]] && continue
    bare=$(echo "$addr" | tr -d '[]')
    if ! echo "$ALL_IPS" | grep -qFx "$bare"; then
        echo "==> Removing stale ListenAddress $addr (not on any local interface)"
        sed -i "/^[[:space:]]*ListenAddress[[:space:]]*${addr//\//\\/}[[:space:]]*$/d" "$CFG"
    fi
done < <(grep -E '^[[:space:]]*ListenAddress[[:space:]]' "$CFG" | awk '{print $2}')

echo "==> Validating new config"
sshd -t || { echo "config invalid; restoring $BACKUP"; cp -p "$BACKUP" "$CFG"; exit 2; }

echo "==> Reloading ssh.service"
systemctl reload ssh.service || systemctl restart ssh.service
sleep 1

echo "==> Effective listeners now:"
ss -tlnp | awk 'NR==1 || /:2222/' | sed 's/^/   /'

if ss -tlnp | grep -E '0\.0\.0\.0:2222|\[::\]:2222' >/dev/null; then
    echo "WARNING: still binding to 0.0.0.0 — config has another stray ListenAddress missing"
fi

cat <<EOF

================================================================
Done. Phone can now reach OpenSSH on:
   ${LAN_IP}:2222   (LAN, only when at home)
   $(tailscale ip -4):2222   (Tailscale, when its routes are visible to Termux)

pivot-up.sh on the phone will try Tailscale first, MagicDNS second, LAN third.

Rollback (puts it back to tailscale-only): sudo bash ~/openssh-rollback.sh
================================================================
EOF
