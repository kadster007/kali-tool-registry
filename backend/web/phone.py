"""Helpers for querying the Fold 6 from kadx via the existing
LAN/Tailscale SSH path. Cached briefly so the dashboard polling
doesn't SSH every second.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

HOME = Path(os.environ.get("HOME", "/home/kadx"))
SSH_KEY = HOME / ".ssh" / "id_ed25519_out"
PHONE_USER = "u0_a559"
PHONE_PORT = "8022"
PHONE_TARGETS = [
    "192.168.1.197",      # last-known LAN
    "100.101.229.113",    # Tailscale
]
SOCKS_PORT = 9050
KADX_PORT = "2222"

_phone_info_cache: Dict = {"ts": 0, "data": None}
_CACHE_SECONDS = 12  # poll backs off so we don't hammer Termux


def _ssh_phone(cmd: str, target: Optional[str] = None, timeout: int = 6) -> subprocess.CompletedProcess:
    targets = [target] if target else PHONE_TARGETS
    last_err: Optional[subprocess.CompletedProcess] = None
    for t in targets:
        try:
            r = subprocess.run(
                [
                    "ssh", "-p", PHONE_PORT,
                    "-i", str(SSH_KEY),
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={timeout}",
                    f"{PHONE_USER}@{t}",
                    cmd,
                ],
                capture_output=True, text=True, timeout=timeout + 3,
            )
            if r.returncode == 0:
                return r
            last_err = r
        except subprocess.TimeoutExpired:
            continue
    if last_err is None:
        last_err = subprocess.CompletedProcess([], 255, "", "unreachable")
    return last_err


def phone_info(force: bool = False) -> Dict:
    """Return phone's current network info. Cached for ~12s."""
    now = time.time()
    if not force and _phone_info_cache["data"] and (now - _phone_info_cache["ts"] < _CACHE_SECONDS):
        return _phone_info_cache["data"]

    r = _ssh_phone(
        # combined: termux-wifi-connectioninfo + cellular check
        "termux-wifi-connectioninfo 2>/dev/null; echo '---'; "
        "termux-telephony-deviceinfo 2>/dev/null | head -20"
    )

    data: Dict = {
        "reachable": False,
        "connection": "unknown",
        "ssid": None,
        "ip": None,
        "frequency_mhz": None,
        "link_speed_mbps": None,
        "rssi": None,
        "cellular_network_type": None,
        "raw_error": None,
        "ts": int(now),
    }

    if r.returncode != 0:
        data["raw_error"] = (r.stderr or "")[:200] or "no path to phone"
        _phone_info_cache.update(ts=now, data=data)
        return data

    data["reachable"] = True
    wifi_blob, _, tel_blob = (r.stdout or "").partition("---")

    # Parse Wi-Fi JSON if present
    try:
        wifi = json.loads(wifi_blob.strip()) if wifi_blob.strip().startswith("{") else {}
    except json.JSONDecodeError:
        wifi = {}
    if wifi and wifi.get("ip") and wifi.get("ip") not in ("0.0.0.0", "<unknown>"):
        data["connection"] = "wifi"
        data["ssid"] = wifi.get("ssid")
        data["ip"] = wifi.get("ip")
        data["frequency_mhz"] = wifi.get("frequency_mhz")
        data["link_speed_mbps"] = wifi.get("link_speed_mbps")
        data["rssi"] = wifi.get("rssi")
    else:
        # Likely cellular — try telephony info
        for line in (tel_blob or "").splitlines():
            line = line.strip().strip(",").strip('"')
            if '"network_type"' in line:
                # crude — Termux returns JSON
                data["connection"] = "cellular"
                try:
                    obj = json.loads("{" + tel_blob.strip().rstrip(",") + "}")
                    data["cellular_network_type"] = obj.get("network_type")
                except Exception:
                    pass
                break
        if data["connection"] == "unknown":
            # Last resort — we know we got SSH, so phone has SOMETHING, just no obvious info
            data["connection"] = "unknown (online)"

    _phone_info_cache.update(ts=now, data=data)
    return data


def autossh_pid() -> Optional[int]:
    """Return autossh PID on the phone, or None."""
    r = _ssh_phone(f"pgrep -fx 'autossh -M 0.*-R[ =]?{SOCKS_PORT}:.*kadx@.*' 2>/dev/null | head -1")
    out = (r.stdout or "").strip()
    return int(out) if out.isdigit() else None


def microsocks_pid() -> Optional[int]:
    r = _ssh_phone(f"pgrep -fx 'microsocks -i 127.0.0.1 -p {SOCKS_PORT}' 2>/dev/null | head -1")
    out = (r.stdout or "").strip()
    return int(out) if out.isdigit() else None


def pivot_release() -> Dict:
    """Kill autossh on the phone. microsocks remains. Tunnel stays down until user restarts."""
    r = _ssh_phone("pkill -f 'autossh.*-R.*9050' 2>/dev/null; echo killed")
    return {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}


def pivot_reset() -> Dict:
    """Kill autossh, then re-launch via the existing pivot-up.sh logic."""
    cmd = (
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null; "
        "sleep 1; "
        "bash $HOME/portable-pivot/frontend/pivot-up.sh </dev/null >/tmp/pivot-up.out 2>&1 &"
    )
    # NOTE: pivot-up.sh ends with `exec autossh` which gives an interactive shell.
    # We don't want interactive here — so we use the menu's start-pivot path instead
    # via a small inline equivalent that runs autossh -fN in background.
    bg_start = (
        "termux-wake-lock 2>/dev/null || true; "
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null; sleep 1; "
        "(pgrep -fx 'microsocks -i 127.0.0.1 -p 9050' >/dev/null || "
        " (nohup microsocks -i 127.0.0.1 -p 9050 >~/microsocks.log 2>&1 & disown)); "
        "sleep 1; "
        "for t in 100.105.140.70 kadx 192.168.1.165; do "
        "  if timeout 4 bash -c \"exec 3<>/dev/tcp/$t/2222\" 2>/dev/null; then "
        "    AUTOSSH_PORT=0 AUTOSSH_GATETIME=0 nohup autossh -M 0 -fN "
        "      -p 2222 -i $HOME/.ssh/id_ed25519 "
        "      -o ServerAliveInterval=10 -o ServerAliveCountMax=2 "
        "      -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=no -o TCPKeepAlive=yes "
        "      -R 9050:127.0.0.1:9050 kadx@$t > /dev/null 2>&1 & disown; "
        "    echo started via $t; exit 0; "
        "  fi; "
        "done; echo 'no kadx target reachable'; exit 1"
    )
    r = _ssh_phone(bg_start, timeout=20)
    return {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}


def pivot_restart_full() -> Dict:
    """Kill both microsocks and autossh, restart everything cleanly."""
    bg_start = (
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null; "
        "pkill -x microsocks 2>/dev/null; "
        "sleep 1; "
    )
    r = _ssh_phone(bg_start + "echo ok", timeout=15)
    if r.returncode != 0:
        return {"ok": False, "output": (r.stdout or "") + (r.stderr or "")}
    # Then bring it back up
    return pivot_reset()


def can_ssh_phone() -> bool:
    r = _ssh_phone("echo ok", timeout=4)
    return r.returncode == 0 and "ok" in r.stdout
