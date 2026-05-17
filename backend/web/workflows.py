"""Workflows: ordered command sequences that feed forward via variables.

Variables supported in step commands:
  {target}      - user-supplied target (from form input or widget)
  {live_hosts}  - comma-separated IPs from latest scan (state=up AND ≥1 open port)
  {service}     - service/product from latest scan (best-effort)
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_FILE = REPO_ROOT / "tools" / "workflows.json"


def load_workflows() -> List[Dict]:
    if not WORKFLOWS_FILE.exists():
        return []
    try:
        d = json.loads(WORKFLOWS_FILE.read_text())
    except json.JSONDecodeError:
        return []
    return d.get("workflows") or []


def get_workflow(wf_id: str) -> Optional[Dict]:
    return next((w for w in load_workflows() if w.get("id") == wf_id), None)


def derive_live_hosts(scan_mod) -> str:
    """Return comma-separated IPs of *truly* live hosts from the latest scan.
    'Truly live' = state=up AND has at least one open port (filters -Pn ghosts)."""
    s = scan_mod.latest_scan()
    if not s:
        return ""
    ips = []
    for h in s.get("hosts") or []:
        if h.get("state") != "up":
            continue
        if not any(p.get("state") == "open" for p in h.get("ports") or []):
            continue
        ips.append(h.get("ip"))
    return ",".join(ips)


def derive_top_service(scan_mod) -> str:
    """Pick the most-recent product+version from latest scan for searchsploit."""
    s = scan_mod.latest_scan()
    if not s:
        return ""
    for h in s.get("hosts") or []:
        for p in h.get("ports") or []:
            if p.get("state") != "open":
                continue
            prod = (p.get("product") or "").strip()
            ver = (p.get("version") or "").strip()
            if prod:
                return (prod + " " + ver).strip()
    return ""


def substitute(cmd: str, target: str, scan_mod) -> str:
    """Replace template variables in the command."""
    if not cmd:
        return ""
    out = cmd
    if "{target}" in out:
        out = out.replace("{target}", target or "")
    if "{live_hosts}" in out:
        out = out.replace("{live_hosts}", derive_live_hosts(scan_mod) or (target or ""))
    if "{service}" in out:
        out = out.replace("{service}", derive_top_service(scan_mod) or "")
    return out
