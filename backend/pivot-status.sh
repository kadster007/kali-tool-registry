#!/usr/bin/env bash
# pivot-status.sh — quick health check of the Fold 6 pivot on kadx (ODIN).
# Run any time:  bash ~/pivot-status.sh

echo "=== Tunnel listener on kadx:9050 (from ssh -R) ==="
ss -tlnp 2>/dev/null | grep ':9050' && echo "  ↑ tunnel ACTIVE" || echo "  ✗ no 9050 listener — no tunnel established (phone needs to run pivot-up.sh)"

echo ""
echo "=== proxychains4 SOCKS endpoint ==="
grep -E '^[[:space:]]*socks' /etc/proxychains4.conf | sed 's/^/  /'

echo ""
echo "=== Phone via Tailscale ==="
tailscale status 2>/dev/null | grep fold6 | sed 's/^/  /' || echo "  (phone not in tailnet status)"

echo ""
echo "=== kadx's direct egress IP (no pivot) ==="
direct=$(curl -sS --max-time 5 https://ifconfig.me 2>/dev/null)
echo "  $direct"

echo ""
echo "=== Phone's egress IP through the pivot (should differ if phone is elsewhere) ==="
if ss -tlnp 2>/dev/null | grep -q ':9050'; then
    pivoted=$(proxychains4 -q curl -sS --max-time 10 https://ifconfig.me 2>/dev/null)
    if [[ -n "$pivoted" ]]; then
        echo "  $pivoted"
        if [[ "$direct" == "$pivoted" ]]; then
            echo "  NOTE: identical to kadx's direct IP — phone is on same WAN (e.g. home). Pivot still works; just same egress."
        else
            echo "  ↑ different IP confirms pivot is routing through phone's distinct network."
        fi
    else
        echo "  ✗ proxychains via pivot failed — microsocks on phone may not be running"
    fi
else
    echo "  (skipped — no tunnel)"
fi
