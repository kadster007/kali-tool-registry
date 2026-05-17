#!/data/data/com.termux/files/usr/bin/bash
# pivot-watchdog.sh — auto-detect phone network changes and re-launch
# the pivot so kadx stops seeing stale tunnels. Designed to run forever
# in the background on the phone.
#
# Usage:
#   nohup ~/portable-pivot/frontend/pivot-watchdog.sh > ~/pivot-watchdog.log 2>&1 &
#   disown
#
# Behavior:
#   * Polls termux-wifi-connectioninfo every CHECK_INTERVAL seconds.
#   * When the phone's IP changes (or comes online from a state where
#     we had no IP), kills the existing autossh (so it can't keep
#     limping along on the dead network), waits briefly for the new
#     network to stabilize, then relaunches pivot-up.sh.
#   * Also restarts pivot when autossh is missing but the phone has
#     a Wi-Fi IP (i.e., process died but network is still up).

set -u

CHECK_INTERVAL="${CHECK_INTERVAL:-7}"
QUIET_AFTER_CHANGE="${QUIET_AFTER_CHANGE:-4}"   # seconds to let DHCP settle
SOCKS_PORT=9050
LOG="$HOME/pivot-watchdog.log"

log() {
    printf '%(%F %T)T  %s\n' -1 "$*" >> "$LOG"
}

current_ip() {
    termux-wifi-connectioninfo 2>/dev/null | awk -F'"' '/"ip":/{print $4}'
}

autossh_running() {
    pgrep -fa "autossh.*-R.*${SOCKS_PORT}.*kadx@" >/dev/null
}

restart_pivot() {
    log "kill autossh + microsocks"
    pkill -f "autossh.*-R.*${SOCKS_PORT}" 2>/dev/null
    pkill -x microsocks 2>/dev/null
    sleep 2
    log "launching pivot-up.sh (-fN background)"
    # Use the non-interactive background-start logic equivalent to menu's start_pivot
    (
        termux-wake-lock 2>/dev/null || true
        nohup microsocks -i 127.0.0.1 -p "${SOCKS_PORT}" > "$HOME/microsocks.log" 2>&1 &
        disown
        sleep 1
        for t in kadx.tailf08ebe.ts.net kadx 100.105.140.70 192.168.1.165; do
            if timeout 4 bash -c "exec 3<>/dev/tcp/$t/2222" 2>/dev/null; then
                AUTOSSH_PORT=0 AUTOSSH_GATETIME=0 \
                    nohup autossh -M 0 -fN \
                        -p 2222 -i "$HOME/.ssh/id_ed25519" \
                        -o ServerAliveInterval=10 -o ServerAliveCountMax=2 \
                        -o StrictHostKeyChecking=accept-new \
                        -o ExitOnForwardFailure=no -o TCPKeepAlive=yes \
                        -R 9050:127.0.0.1:9050 \
                        -R 8022:127.0.0.1:8022 \
                        "kadx@$t" > /dev/null 2>&1 &
                disown
                log "autossh launched via $t"
                return 0
            fi
            log "  $t unreachable (TCP 2222)"
        done
        log "no kadx target reachable; will retry next cycle"
        return 1
    )
}

log "watchdog starting (interval=${CHECK_INTERVAL}s)"
PREV_IP=""

while true; do
    CUR_IP="$(current_ip)"

    if [ -z "$CUR_IP" ] || [ "$CUR_IP" = "0.0.0.0" ] || [ "$CUR_IP" = "<unknown>" ]; then
        # No Wi-Fi IP — phone may be on cellular only or screen off.
        # Don't churn; just wait.
        if [ -n "$PREV_IP" ]; then
            log "lost Wi-Fi IP (was $PREV_IP)"
            PREV_IP=""
        fi
        sleep "$CHECK_INTERVAL"
        continue
    fi

    if [ "$CUR_IP" != "$PREV_IP" ]; then
        if [ -z "$PREV_IP" ]; then
            log "IP appeared: $CUR_IP"
        else
            log "IP changed: $PREV_IP -> $CUR_IP — pivot needs rebuild"
        fi
        sleep "$QUIET_AFTER_CHANGE"
        restart_pivot
        PREV_IP="$CUR_IP"
    elif ! autossh_running; then
        # Same IP but no autossh — process died, restart it
        log "autossh missing while IP=$CUR_IP — restarting"
        restart_pivot
    fi

    sleep "$CHECK_INTERVAL"
done
