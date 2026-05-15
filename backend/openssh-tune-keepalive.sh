#!/usr/bin/env bash
# Tune kadx's sshd keepalive so port 9050 is released quickly after the
# phone changes networks. Idempotent; run as root.
#
# Run:  sudo bash ~/portable-pivot/backend/openssh-tune-keepalive.sh

set -euo pipefail

CFG=/etc/ssh/sshd_config
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="${CFG}.bak.tune.${STAMP}"

echo "==> Backing up $CFG -> $BACKUP"
cp -p "$CFG" "$BACKUP"
echo "$BACKUP" > /etc/ssh/.last-backup

set_directive() {
    local key="$1" val="$2"
    if grep -qE "^[[:space:]]*${key}[[:space:]]" "$CFG"; then
        sed -i -E "s|^[[:space:]]*${key}[[:space:]].*|${key} ${val}|" "$CFG"
    else
        printf '\n%s %s\n' "$key" "$val" >> "$CFG"
    fi
}

set_directive ClientAliveInterval 15
set_directive ClientAliveCountMax 2
set_directive TCPKeepAlive yes

echo "==> Validating"
sshd -t || { echo "config invalid; restoring"; cp -p "$BACKUP" "$CFG"; exit 2; }

echo "==> Reloading ssh.service"
systemctl reload ssh.service || systemctl restart ssh.service

echo "==> Effective values now:"
sshd -T 2>/dev/null | grep -iE "^(clientaliveinterval|clientalivecountmax|tcpkeepalive)" | sed 's/^/   /'

cat <<EOF

================================================================
sshd now detects dead -R clients in ~30 seconds (was 180).
Port 9050 will be released for autossh's reconnect that much faster.
Backup at: $BACKUP
================================================================
EOF
