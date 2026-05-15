#!/usr/bin/env bash
# Tailscale "portable PC" setup for kadx.
# Makes this i9-9900K Kali box reachable from the Fold 6 via Tailscale SSH
# and usable as an exit node for the phone.
#
# Review, then run:  sudo bash ~/tailscale-setup.sh
set -euo pipefail

echo "==> 1/4  Persisting IPv4 + IPv6 forwarding (required for exit node)"
install -m 0644 /dev/stdin /etc/sysctl.d/99-tailscale.conf <<'EOF'
# Tailscale exit-node forwarding
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl --system >/dev/null
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding

echo
echo "==> 2/4  Applying UDP GRO offload (improves exit-node throughput)"
NIC=$(ip -o route get 8.8.8.8 | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
echo "    egress NIC: $NIC"
ethtool -K "$NIC" rx-udp-gro-forwarding on rx-gro-list off 2>&1 || \
  echo "    (warning: NIC may not support UDP GRO; non-fatal)"

# Persist via NetworkManager dispatcher so it survives reboot.
cat >/etc/NetworkManager/dispatcher.d/50-tailscale-gro <<EOF
#!/bin/sh
# Re-apply UDP GRO offload on Tailscale's egress NIC after NM events.
[ "\$1" = "$NIC" ] || exit 0
case "\$2" in
  up|connectivity-change) ethtool -K "$NIC" rx-udp-gro-forwarding on rx-gro-list off ;;
esac
EOF
chmod +x /etc/NetworkManager/dispatcher.d/50-tailscale-gro

echo
echo "==> 3/4  Advertising kadx as Tailscale exit node"
echo "    (Tailscale SSH is already enabled; preserving it.)"
tailscale set --advertise-exit-node --ssh

echo
echo "==> 4/4  Status"
tailscale status | head -20

cat <<'EOF'

==============================================================
DONE on this machine. Two manual steps remain:

1) APPROVE the exit node in the admin console:
   https://login.tailscale.com/admin/machines
   - Click "kadx" -> "Edit route settings" -> check "Use as exit node" -> Save

2) On the Fold 6, in the Tailscale app:
   - Settings -> Use exit node -> pick "kadx"
   - Verify by visiting https://ifconfig.me  in Chrome on the phone;
     it should show this PC's home WAN IP, not the cell carrier IP.

For SSH from the Fold 6:
   - Install Termux from F-Droid, then:  pkg install openssh
   - ssh kadx@kadx        (or  ssh kadx@100.105.140.70 )
   - Tailscale SSH = no key setup needed; auth is handled by the tailnet.
==============================================================
EOF
