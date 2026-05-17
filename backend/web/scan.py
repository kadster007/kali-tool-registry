"""nmap XML parser + cross-scan aggregation.

We read every *.xml under ~/pivot-logs/, merge ports/services per IP,
and surface that to the web UI as structured host records.
"""
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

HOME = Path(os.environ.get("HOME", "/home/kadx"))
LOGS_DIR = HOME / "pivot-logs"


def parse_nmap_xml(p: Path) -> Optional[Dict]:
    """Parse one nmap XML file -> structured dict. Returns None on parse error."""
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError:
        return None

    hosts: List[Dict] = []
    for h in root.findall("host"):
        addrs = {a.get("addrtype"): a.get("addr") for a in h.findall("address")}
        ip = addrs.get("ipv4") or addrs.get("ipv6") or "?"
        hostnames = [
            hn.get("name") for hn in h.findall("hostnames/hostname")
            if hn.get("name")
        ]
        status = h.find("status")
        state = status.get("state") if status is not None else "?"
        ports = []
        for p_el in h.findall("ports/port"):
            portid = p_el.get("portid")
            proto = p_el.get("protocol")
            state_el = p_el.find("state")
            service_el = p_el.find("service")
            scripts = []
            for s in p_el.findall("script"):
                scripts.append({
                    "id": s.get("id"),
                    "output": s.get("output"),
                })
            ports.append({
                "port": int(portid) if portid else 0,
                "proto": proto,
                "state": state_el.get("state") if state_el is not None else "?",
                "service": service_el.get("name") if service_el is not None else None,
                "product": service_el.get("product") if service_el is not None else None,
                "version": service_el.get("version") if service_el is not None else None,
                "extrainfo": service_el.get("extrainfo") if service_el is not None else None,
                "scripts": scripts,
            })
        os_match = h.find("os/osmatch")
        os_name = os_match.get("name") if os_match is not None else None

        # host-level scripts (vulners, vuln, etc.)
        host_scripts = []
        for s in h.findall("hostscript/script"):
            host_scripts.append({"id": s.get("id"), "output": s.get("output")})

        hosts.append({
            "ip": ip,
            "mac": addrs.get("mac"),
            "hostnames": hostnames,
            "state": state,
            "ports": ports,
            "os": os_name,
            "host_scripts": host_scripts,
        })

    return {
        "args": root.get("args"),
        "scaninfo": root.find("scaninfo").get("type") if root.find("scaninfo") is not None else None,
        "started": root.get("startstr"),
        "hosts": hosts,
        "file": str(p),
        "file_mtime": int(p.stat().st_mtime),
    }


def _ip_sort_key(ip: str):
    """Sort IPs numerically; fall back to lexical for IPv6/odd entries."""
    try:
        return (0, *[int(o) for o in ip.split(".")])
    except (ValueError, AttributeError):
        return (1, ip or "")


def all_xml_files() -> List[Path]:
    if not LOGS_DIR.exists():
        return []
    return sorted(LOGS_DIR.glob("*/*.xml"), key=lambda p: p.stat().st_mtime, reverse=True)


def all_hosts() -> Dict[str, Dict]:
    """Aggregate hosts across all scans. Latest data wins for duplicate ports."""
    out: Dict[str, Dict] = {}
    for xml in all_xml_files():
        scan = parse_nmap_xml(xml)
        if not scan:
            continue
        scan_ts = scan["file_mtime"]
        for h in scan["hosts"]:
            ip = h["ip"]
            if ip not in out:
                out[ip] = {
                    "ip": ip,
                    "mac": h.get("mac"),
                    "hostnames": list(h.get("hostnames") or []),
                    "state": h.get("state"),
                    "os": h.get("os"),
                    "ports_by_key": {},
                    "host_scripts": list(h.get("host_scripts") or []),
                    "sources": [],
                    "first_seen": scan_ts,
                    "last_seen": scan_ts,
                }
            rec = out[ip]
            rec["last_seen"] = max(rec["last_seen"], scan_ts)
            rec["sources"].append({"file": scan["file"], "ts": scan_ts, "args": scan.get("args")})
            for hn in h.get("hostnames") or []:
                if hn not in rec["hostnames"]:
                    rec["hostnames"].append(hn)
            if h.get("mac") and not rec.get("mac"):
                rec["mac"] = h["mac"]
            if h.get("os") and not rec.get("os"):
                rec["os"] = h["os"]
            for p in h.get("ports") or []:
                rec["ports_by_key"][(p["port"], p["proto"])] = p
            for s in h.get("host_scripts") or []:
                rec["host_scripts"].append(s)

    # Flatten ports_by_key into a sorted list
    for ip, rec in out.items():
        ports = list(rec.pop("ports_by_key").values())
        ports.sort(key=lambda p: (p.get("proto") or "", p.get("port") or 0))
        rec["ports"] = ports
        # Deduplicate host_scripts by id
        seen = set()
        uniq_hs = []
        for s in rec["host_scripts"]:
            key = (s.get("id"), s.get("output") or "")
            if key not in seen:
                seen.add(key)
                uniq_hs.append(s)
        rec["host_scripts"] = uniq_hs
    return out


def hosts_sorted() -> List[Dict]:
    h = all_hosts()
    return sorted(h.values(), key=lambda r: _ip_sort_key(r["ip"]))


def host_by_ip(ip: str) -> Optional[Dict]:
    return all_hosts().get(ip)


def latest_scan() -> Optional[Dict]:
    """Parse the most-recent XML file. Returns a single scan dict
    (not aggregated across files) — the live 'current scan' surface.
    """
    files = all_xml_files()
    if not files:
        return None
    return parse_nmap_xml(files[0])


def scan_list() -> List[Dict]:
    """List every XML scan file with a quick summary (no full parse)."""
    out = []
    for p in all_xml_files():
        try:
            stat = p.stat()
        except OSError:
            continue
        scan = parse_nmap_xml(p) or {}
        hosts = scan.get("hosts") or []
        up = sum(1 for h in hosts if h.get("state") == "up")
        out.append({
            "file": str(p),
            "name": p.name,
            "mtime": int(stat.st_mtime),
            "hosts_total": len(hosts),
            "hosts_up": up,
            "args": (scan.get("args") or "")[:80],
        })
    return out


def hosts_from_scan(scan: Optional[Dict]) -> List[Dict]:
    """Flatten a single parsed scan into the same shape as hosts_sorted()."""
    if not scan:
        return []
    out = []
    for h in scan.get("hosts") or []:
        # Normalize shape to match aggregated hosts (include sources field).
        ports = list(h.get("ports") or [])
        ports.sort(key=lambda p: (p.get("proto") or "", p.get("port") or 0))
        out.append({
            "ip": h.get("ip"),
            "mac": h.get("mac"),
            "hostnames": list(h.get("hostnames") or []),
            "state": h.get("state"),
            "os": h.get("os"),
            "ports": ports,
            "host_scripts": list(h.get("host_scripts") or []),
            "sources": [{"file": scan.get("file"), "ts": scan.get("file_mtime"), "args": scan.get("args")}],
            "first_seen": scan.get("file_mtime"),
            "last_seen": scan.get("file_mtime"),
        })
    out.sort(key=lambda r: _ip_sort_key(r["ip"]))
    return out


def scan_by_file(file_path: str) -> Optional[Dict]:
    """Look up a scan by its file path; returns parsed dict or None."""
    from os.path import abspath
    target = abspath(file_path)
    for p in all_xml_files():
        if abspath(str(p)) == target:
            return parse_nmap_xml(p)
    return None
