"""
Phone control: routed exclusively through the autossh -R 8022 reverse
tunnel established by pivot-up.sh / the frontend menu.

The phone never needs to be directly reachable by IP. As long as the
pivot tunnel is up, `kadx:127.0.0.1:8022` is the phone's sshd.
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
PHONE_SSH_HOST = "127.0.0.1"
PHONE_SSH_PORT = "8022"
SOCKS_PORT = 9050

_phone_info_cache: Dict = {"ts": 0, "data": None}
_CACHE_SECONDS = 12


def _ssh_phone(cmd: str, timeout: int = 6) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [
                "ssh", "-p", PHONE_SSH_PORT,
                "-i", str(SSH_KEY),
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                f"{PHONE_USER}@{PHONE_SSH_HOST}",
                cmd,
            ],
            capture_output=True, text=True, timeout=timeout + 3,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 124, "", "timeout")


def _subnet_24(ip: Optional[str]) -> Optional[str]:
    if not ip or not isinstance(ip, str):
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        [int(p) for p in parts]
    except ValueError:
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def phone_info(force: bool = False) -> Dict:
    """Returns phone network state via the tunnel-routed SSH."""
    now = time.time()
    if not force and _phone_info_cache["data"] and (now - _phone_info_cache["ts"] < _CACHE_SECONDS):
        return _phone_info_cache["data"]

    r = _ssh_phone(
        "termux-wifi-connectioninfo 2>/dev/null; "
        "echo '---'; "
        "termux-telephony-deviceinfo 2>/dev/null"
    )

    data: Dict = {
        "reachable": False,
        "connection": "unknown",
        "ssid": None,
        "ip": None,
        "subnet": None,
        "frequency_mhz": None,
        "link_speed_mbps": None,
        "rssi": None,
        "cellular_network_type": None,
        "raw_error": None,
        "ts": int(now),
    }

    if r.returncode != 0:
        data["raw_error"] = (
            "tunnel-routed SSH failed: " + ((r.stderr or "").strip() or "no path") +
            " — is the pivot tunnel up with -R 8022?"
        )
        _phone_info_cache.update(ts=now, data=data)
        return data

    data["reachable"] = True
    wifi_blob, _, tel_blob = (r.stdout or "").partition("---")

    try:
        wifi = json.loads(wifi_blob.strip()) if wifi_blob.strip().startswith("{") else {}
    except json.JSONDecodeError:
        wifi = {}
    if wifi and wifi.get("ip") and wifi.get("ip") not in ("0.0.0.0", "<unknown>"):
        data["connection"] = "wifi"
        data["ssid"] = wifi.get("ssid")
        data["ip"] = wifi.get("ip")
        data["subnet"] = _subnet_24(data["ip"])
        data["frequency_mhz"] = wifi.get("frequency_mhz")
        data["link_speed_mbps"] = wifi.get("link_speed_mbps")
        data["rssi"] = wifi.get("rssi")
    else:
        try:
            tel = json.loads(tel_blob.strip()) if tel_blob.strip().startswith("{") else {}
        except json.JSONDecodeError:
            tel = {}
        if tel:
            data["connection"] = "cellular"
            data["cellular_network_type"] = tel.get("network_type")
        else:
            data["connection"] = "unknown (online)"

    _phone_info_cache.update(ts=now, data=data)
    return data


# ---- pivot tunnel control on the phone ---------------------------------

_PHONE_AUTOSSH_PATTERN = "autossh.*-R.*9050.*-R.*8022.*kadx@"


def autossh_running() -> bool:
    r = _ssh_phone(f"pgrep -fa '{_PHONE_AUTOSSH_PATTERN}' >/dev/null && echo yes")
    return "yes" in (r.stdout or "")


def microsocks_running() -> bool:
    r = _ssh_phone(f"pgrep -fx 'microsocks -i 127.0.0.1 -p {SOCKS_PORT}' >/dev/null && echo yes")
    return "yes" in (r.stdout or "")


def pivot_release() -> Dict:
    r = _ssh_phone("pkill -f 'autossh.*-R.*9050' 2>/dev/null; echo done")
    return {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}


def _bg_start() -> str:
    # Background autossh, with BOTH reverse tunnels (-R 9050, -R 8022).
    # Target order matches pivot-up.sh: FQDN -> short -> Tailscale IP -> LAN.
    return (
        "termux-wake-lock 2>/dev/null || true; "
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null; sleep 1; "
        "(pgrep -fx 'microsocks -i 127.0.0.1 -p 9050' >/dev/null || "
        " (nohup microsocks -i 127.0.0.1 -p 9050 >~/microsocks.log 2>&1 & disown)); "
        "sleep 1; "
        "for t in kadx.tailf08ebe.ts.net kadx 100.105.140.70 192.168.1.165; do "
        "  if timeout 4 bash -c \"exec 3<>/dev/tcp/$t/2222\" 2>/dev/null; then "
        "    AUTOSSH_PORT=0 AUTOSSH_GATETIME=0 nohup autossh -M 0 -fN "
        "      -p 2222 -i $HOME/.ssh/id_ed25519 "
        "      -o ServerAliveInterval=10 -o ServerAliveCountMax=2 "
        "      -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=no -o TCPKeepAlive=yes "
        "      -R 9050:127.0.0.1:9050 -R 8022:127.0.0.1:8022 kadx@$t > /dev/null 2>&1 & disown; "
        "    echo started via $t; exit 0; "
        "  fi; "
        "done; echo 'no kadx target reachable'; exit 1"
    )


def pivot_reset() -> Dict:
    """The phone can do this entirely on its own; we just send the script over the tunnel."""
    r = _ssh_phone(_bg_start(), timeout=20)
    return {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}


def pivot_restart_full() -> Dict:
    r = _ssh_phone(
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null; "
        "pkill -x microsocks 2>/dev/null; "
        "sleep 1; echo ok",
        timeout=10,
    )
    if r.returncode != 0:
        return {"ok": False, "output": (r.stdout or "") + (r.stderr or "")}
    return pivot_reset()


def can_ssh_phone() -> bool:
    r = _ssh_phone("echo ok", timeout=4)
    return r.returncode == 0 and "ok" in r.stdout


def pivot_start() -> Dict:
    """Same as pivot_reset() — kicks the phone via tunnel-routed SSH to launch autossh.
    Returns ok=False with fallback_command if we can't reach the phone at all."""
    if not can_ssh_phone():
        return {
            "ok": False,
            "fallback_command": "~/portable-pivot/frontend/pivot-up.sh",
            "output": "Tunnel-routed SSH unreachable. Run the command in Termux on the phone.",
        }
    return pivot_reset()
