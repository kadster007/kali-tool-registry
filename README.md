# FieldOps — Distributed Pentest Platform

Mobile-first penetration testing platform. Fold6 (NetHunter) as the field agent, KALIWARE as the remote execution engine, connected via Tailscale VPN.

## Architecture

```
[Fold6 Browser/KEX]  ←→  [Tailscale VPN]  ←→  [KALIWARE :5001]
     Frontend                                    Backend + Tools
```

## Tool Registry

`tools/` contains one JSON file per tool with:
- Flags and options (with types, descriptions, examples)
- Preset commands (common use cases, one-tap)
- Notes and gotchas
- Example commands

`tools/registry.json` is the master index with categories, tool list, and **playbooks** (automated multi-step workflows).

## Playbooks

Automated workflows that chain tools together, save results to a **Target Profile** (JSON), and feed output from one tool into the next automatically:

| Playbook | Steps | What it finds |
|---|---|---|
| Full LAN Discovery | ARP → masscan → nmap → SMB check → NetBIOS | All hosts, ports, services, shares, OS |
| Quick Host Map | ARP sweep only | Live hosts + MAC/vendor in <10s |
| SMB Audit | nmap 445 → smbmap → enum4linux | All Windows shares and users |

## Phase 1 — LAN Tools

| Tool | Category | Root | Purpose |
|---|---|---|---|
| nmap | Discovery | optional | Port scan, service/OS detection, NSE scripts |
| masscan | Discovery | yes | Ultra-fast port sweep |
| arp-scan | Discovery | yes | ARP host discovery |
| netdiscover | Discovery | yes | ARP recon with vendor ID |
| fping | Discovery | no | Fast ICMP host sweep |
| nbtscan | Enumeration | no | NetBIOS names + workgroup |
| enum4linux | Enumeration | no | SMB/Windows full enumeration |
| smbmap | Enumeration | no | SMB share listing + file access |
| hydra | Credential Testing | no | Network service brute force |
| hping3 | Network Testing | yes | Custom packet crafting |

## Target Profile Format

Each engagement saves a `target_profile.json`:
```json
{
  "engagement_id": "home-lan-2026-05-02",
  "subnet": "192.168.1.0/24",
  "hosts": [
    {
      "ip": "192.168.1.1",
      "mac": "aa:bb:cc:11:22:33",
      "vendor": "Netgear",
      "hostname": "router.local",
      "os": "Linux 3.x",
      "open_ports": [
        {"port": 80, "service": "http", "version": "nginx 1.18"}
      ],
      "smb_shares": []
    }
  ]
}
```

This profile is the input for Phase 2 tools — select a host, the tool pre-fills IP and discovered open ports.
