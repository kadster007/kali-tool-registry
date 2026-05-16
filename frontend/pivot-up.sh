#!/data/data/com.termux/files/usr/bin/bash
# pivot-up.sh — portable pivot launcher with autossh + multi-target fallback.
# Target order: Tailscale IP -> MagicDNS name -> LAN IP.

set -u

KADX_TARGETS=(
    "kadx.tailf08ebe.ts.net"   # FQDN — preferred (works anywhere Tailscale + MagicDNS are functional)
    "kadx"                      # MagicDNS short name — same path with shorter spelling
    "100.105.140.70"            # Hardcoded Tailscale IP — bypasses DNS but still needs Tailscale route
    "192.168.1.165"             # LAN IP — only works when phone is on the same Wi-Fi as kadx
)
KADX_PORT="2222"
KADX_USER="kadx"
KADX_KEY="$HOME/.ssh/id_ed25519"
SOCKS_PORT="9050"           # phone microsocks (the network-pivot SOCKS5)
PHONE_SSHD_PORT="8022"      # phone Termux sshd (dedicated control channel)
AUTOSSH_LOG="$HOME/.autossh.log"

echo "==> wakelock"
termux-wake-lock 2>/dev/null || true

# microsocks
echo "==> microsocks on 127.0.0.1:$SOCKS_PORT"
if pgrep -fx "microsocks -i 127.0.0.1 -p $SOCKS_PORT" >/dev/null; then
    echo "   already running (pid $(pgrep -fx "microsocks -i 127.0.0.1 -p $SOCKS_PORT"))"
else
    nohup microsocks -i 127.0.0.1 -p "$SOCKS_PORT" > "$HOME/microsocks.log" 2>&1 &
    disown
    sleep 1
    pgrep -fx "microsocks -i 127.0.0.1 -p $SOCKS_PORT" >/dev/null \
        || { echo "FAILED to start microsocks"; exit 1; }
    echo "   started (pid $(pgrep -fx "microsocks -i 127.0.0.1 -p $SOCKS_PORT"))"
fi

# pick a reachable kadx target — with per-target diagnostics so the user
# can see exactly which step failed if all targets fail (esp. on cellular)
echo "==> finding a reachable kadx target..."
PICKED=""
for t in "${KADX_TARGETS[@]}"; do
    printf "   %-30s " "$t"
    # 1. DNS resolution (skip if already an IP)
    if [[ "$t" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        resolved="(ip)"
    else
        resolved=$(getent hosts "$t" 2>/dev/null | awk '{print $1}' | head -1)
        if [ -z "$resolved" ]; then
            # busybox / Termux often lacks getent — try ping name resolution
            resolved=$(ping -c 1 -W 1 -q "$t" 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        fi
        [ -z "$resolved" ] && resolved="DNS-FAIL"
    fi
    # 2. TCP probe to port 2222
    if [ "$resolved" = "DNS-FAIL" ]; then
        echo "✗ ($resolved)"
        continue
    fi
    if timeout 4 bash -c "exec 3<>/dev/tcp/$t/$KADX_PORT" 2>/dev/null; then
        echo "✓ TCP OK   ($resolved:$KADX_PORT)"
        PICKED="$t"
        break
    else
        echo "✗ TCP timeout/refused ($resolved:$KADX_PORT)"
    fi
done

if [ -z "$PICKED" ]; then
    cat <<EOF

==> ERROR: no kadx target is reachable from this phone.

Likely causes (in order of probability):

  1. Termux can't see Tailscale's routes — known Termux+Android+Tailscale
     issue. Try (in the Tailscale Android app):
       * Toggle exit-node to "None"
       * Toggle Tailscale OFF then back ON
       * Android Settings -> Network -> VPN -> Tailscale -> Always-on VPN

  2. You're on cellular and Tailscale isn't establishing direct or relayed
     paths. Look at the Tailscale app: it should show "Connected".

  3. The phone is on home Wi-Fi but on a different subnet than kadx (e.g.
     behind the TP-Link AP at 192.168.0.x while kadx is on 192.168.1.x).
     In that case LAN fallback won't work either; only Tailscale will,
     and that's blocked by #1.

  4. Sshd on kadx is down. From any device that CAN reach kadx:
       ss -tlnp | grep ':2222'
EOF
    exit 2
fi

# kill any old tunnel processes
pkill -f "ssh.*-R[ =]?$SOCKS_PORT:.*${KADX_USER}@" 2>/dev/null || true
pkill -f "autossh.*-R[ =]?$SOCKS_PORT:.*${KADX_USER}@" 2>/dev/null || true

echo "==> opening autossh tunnel + interactive kadx shell via $PICKED"
echo "   autossh will auto-reconnect if the network blips."
echo "   Ctrl-D or 'exit' to leave the shell. To kill the tunnel:  pkill autossh"
# AUTOSSH_PORT=0 disables the monitor port; we use SSH keepalives instead.
# AUTOSSH_GATETIME=0 allows rapid retries after disconnect (default 30s gate
# would make autossh give up if ssh died before 30s — bad during reconnects).
# ExitOnForwardFailure=no: if the remote port is briefly still bound by the
# previous (dying) session, keep trying instead of bailing out.
exec env AUTOSSH_PORT=0 AUTOSSH_GATETIME=0 AUTOSSH_LOGFILE="$AUTOSSH_LOG" \
    autossh -M 0 \
        -p "$KADX_PORT" -i "$KADX_KEY" \
        -o ServerAliveInterval=10 -o ServerAliveCountMax=2 \
        -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=no \
        -o TCPKeepAlive=yes \
        -R "$SOCKS_PORT:127.0.0.1:$SOCKS_PORT" \
        -R "$PHONE_SSHD_PORT:127.0.0.1:$PHONE_SSHD_PORT" \
        "$KADX_USER@$PICKED"
