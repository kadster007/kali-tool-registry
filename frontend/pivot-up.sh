#!/data/data/com.termux/files/usr/bin/bash
# pivot-up.sh — portable pivot launcher with autossh + multi-target fallback.
# Target order: Tailscale IP -> MagicDNS name -> LAN IP.

set -u

KADX_TARGETS=(
    "100.105.140.70"     # Tailscale IP — works anywhere if Tailscale routes are visible
    "kadx"               # MagicDNS — sometimes resolves when bare IP doesn't
    "192.168.1.165"      # LAN IP — works only when phone is on home Wi-Fi
)
KADX_PORT="2222"
KADX_USER="kadx"
KADX_KEY="$HOME/.ssh/id_ed25519"
SOCKS_PORT="9050"
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

# pick a reachable kadx target
echo "==> finding a reachable kadx target..."
PICKED=""
for t in "${KADX_TARGETS[@]}"; do
    printf "   trying %s ... " "$t"
    if timeout 4 bash -c "exec 3<>/dev/tcp/$t/$KADX_PORT" 2>/dev/null; then
        echo "REACHABLE"
        PICKED="$t"
        break
    else
        echo "no route / timeout"
    fi
done

if [ -z "$PICKED" ]; then
    cat <<EOF
==> ERROR: no kadx target is reachable from this phone.
    Check Tailscale on phone (toggle off/on; ensure exit-node is OFF).
    If at home, confirm you're on the same Wi-Fi as kadx.
EOF
    exit 2
fi

# kill any old tunnel processes
pkill -f "ssh.*-R[ =]?$SOCKS_PORT:.*${KADX_USER}@" 2>/dev/null || true
pkill -f "autossh.*-R[ =]?$SOCKS_PORT:.*${KADX_USER}@" 2>/dev/null || true

echo "==> opening autossh tunnel + interactive kadx shell via $PICKED"
echo "   autossh will auto-reconnect if the network blips."
echo "   Ctrl-D or 'exit' to leave the shell. To kill the tunnel:  pkill autossh"
# AUTOSSH_PORT=0 disables the monitor port; we use SSH keepalives instead
exec env AUTOSSH_PORT=0 AUTOSSH_LOGFILE="$AUTOSSH_LOG" \
    autossh -M 0 \
        -p "$KADX_PORT" -i "$KADX_KEY" \
        -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
        -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=yes \
        -R "$SOCKS_PORT:127.0.0.1:$SOCKS_PORT" \
        "$KADX_USER@$PICKED"
