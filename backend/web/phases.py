"""Standard pentest phases. Tools are bucketed by their JSON `category` field."""
import json
from pathlib import Path
from typing import Dict, List

PHASES = [
    {
        "id": 1, "name": "Recon",
        "blurb": "Passive & active information gathering",
        "categories": ["recon", "osint", "footprinting"],
    },
    {
        "id": 2, "name": "Network Scanning",
        "blurb": "Host & port discovery",
        "categories": ["network-discovery", "network-testing", "port-scanning"],
    },
    {
        "id": 3, "name": "Enumeration",
        "blurb": "Services, shares, users",
        "categories": ["enumeration", "service-detection"],
    },
    {
        "id": 4, "name": "Vulnerability Assessment",
        "blurb": "CVE matching, weak services",
        "categories": ["vulnerability", "vuln-scanning"],
    },
    {
        "id": 5, "name": "Exploitation",
        "blurb": "Credential testing, exploits",
        "categories": ["credential-testing", "exploitation", "brute-force"],
    },
    {
        "id": 6, "name": "Post-Exploitation",
        "blurb": "Pivoting, persistence",
        "categories": ["post-exploit", "pivoting"],
    },
    {
        "id": 7, "name": "Reporting",
        "blurb": "Collect & format findings",
        "categories": ["reporting"],
    },
]


def load_tools(tools_dir: Path) -> List[Dict]:
    tools = []
    if not tools_dir.exists():
        return tools
    for p in sorted(tools_dir.glob("*.json")):
        if p.name == "registry.json":
            continue
        try:
            d = json.loads(p.read_text())
            d["_id"] = p.stem
            d["_file"] = p.name
            tools.append(d)
        except Exception as e:
            tools.append({"_id": p.stem, "_file": p.name, "_error": str(e), "name": p.stem})
    return tools


def phases_with_tools(tools_dir: Path) -> List[Dict]:
    tools = load_tools(tools_dir)
    phases = []
    for ph in PHASES:
        bucket = []
        for t in tools:
            cat = (t.get("category") or "").lower()
            if cat in ph["categories"]:
                bucket.append(t)
        phases.append({**ph, "tools": bucket})
    return phases
