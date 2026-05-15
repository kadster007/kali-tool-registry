#!/usr/bin/env bash
# OpenSSH setup for ODIN (kadx) — for SSH port-forwarding (the -R tunnels
# Tailscale's built-in SSH can't carry).
#
# Safe defaults:
#   - Bound to tailscale0 interface only — never on LAN or public internet
#   - Listens on port 2222 (so Tailscale SSH stays as-is on 22)
#   - Public-key auth only — no password, no root
#   - AllowTcpForwarding yes (so `ssh -R` works)
#
# Run:    sudo bash ~/openssh-setup.sh
# Undo:   sudo bash ~/openssh-rollback.sh

set -euo pipefail

CFG=/etc/ssh/sshd_config
TS_V4=$(tailscale ip -4 2>/dev/null || echo "")
TS_V6=$(tailscale ip -6 2>/dev/null || echo "")
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="${CFG}.bak.${STAMP}"

if [[ -z "$TS_V4" ]]; then
    echo "ERROR: tailscale doesn't report a v4 IP. Is tailscale up?"
    exit 1
fi

echo "==> 1/6  Backing up sshd_config to: $BACKUP"
cp -p "$CFG" "$BACKUP"

# Record the backup path for the rollback script to find later.
echo "$BACKUP" > /etc/ssh/.last-backup

echo "==> 2/6  Writing hardened sshd_config (key-only, tailnet-only, port 2222)"
cat > "$CFG" <<EOF
# /etc/ssh/sshd_config — managed by openssh-setup.sh on ${STAMP}
# Original config preserved at: ${BACKUP}

Port 2222

# Bind ONLY to the Tailscale interface — never the LAN or 0.0.0.0
ListenAddress ${TS_V4}
$(if [[ -n "$TS_V6" ]]; then echo "ListenAddress ${TS_V6}"; fi)

# Auth: public-key only, no root, no password attempts
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM yes

# Forwarding: enable -R/-L/-D since this server's whole purpose is to carry tunnels
AllowTcpForwarding yes
GatewayPorts no
X11Forwarding no
PermitTunnel no
AllowAgentForwarding yes

# Misc
LoginGraceTime 30
MaxAuthTries 3

# Detect-and-evict dead clients quickly so port 9050 (used by ssh -R from
# the phone) is released within ~30s when the phone changes networks.
ClientAliveInterval 15
ClientAliveCountMax 2
TCPKeepAlive yes

Subsystem sftp /usr/lib/openssh/sftp-server
EOF

echo "==> 3/6  Ensuring ~kadx/.ssh exists with correct permissions"
install -d -m 0700 -o kadx -g kadx /home/kadx/.ssh
touch /home/kadx/.ssh/authorized_keys
chmod 0600 /home/kadx/.ssh/authorized_keys
chown kadx:kadx /home/kadx/.ssh/authorized_keys

echo "==> 4/6  Validating sshd_config (sshd -t)"
if ! sshd -t; then
    echo "ERROR: sshd config validation FAILED. Restoring backup."
    cp -p "$BACKUP" "$CFG"
    exit 2
fi
echo "    config OK"

echo "==> 5/6  Enabling and starting ssh.service"
systemctl enable ssh.service
systemctl restart ssh.service
sleep 1
if ! systemctl is-active --quiet ssh.service; then
    echo "ERROR: ssh.service failed to start. Restoring backup."
    cp -p "$BACKUP" "$CFG"
    systemctl disable --now ssh.service 2>/dev/null || true
    exit 3
fi

echo "==> 6/6  Verifying listener is bound to tailscale ONLY"
echo "    expected: only 100.x or fd7a:* addresses on :2222 — never 0.0.0.0"
ss -tlnp | awk 'NR==1 || /:2222/' | sed 's/^/    /'

if ss -tlnp | grep -E '0\.0\.0\.0:2222|\[::\]:2222' >/dev/null; then
    echo "ERROR: ssh is binding to 0.0.0.0 — REFUSING to leave running"
    systemctl stop ssh.service
    cp -p "$BACKUP" "$CFG"
    exit 4
fi

cat <<EOF

================================================================
OpenSSH is up on port 2222, tailnet-only.

NEXT STEPS (do these on the Fold 6 via Termux):

  1) Generate a key on the phone:
        ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

  2) Show its public half:
        cat ~/.ssh/id_ed25519.pub

  3) Add that public key to ODIN's authorized_keys. Easiest way:
     from the phone, use Tailscale's built-in passwordless SSH to ODIN
     (port 22) and append it in one line:

        ssh kadx@${TS_V4} "cat >> ~/.ssh/authorized_keys" < ~/.ssh/id_ed25519.pub

  4) Test the new OpenSSH path (port 2222):
        ssh -p 2222 kadx@${TS_V4}

     ...and the actual pivot setup (microsocks running first):
        ssh -p 2222 -R 9050:127.0.0.1:9050 kadx@${TS_V4}

ROLLBACK if anything goes wrong:
  sudo bash ~/openssh-rollback.sh
================================================================
EOF
