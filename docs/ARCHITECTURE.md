# Architecture

## Diagram

```
        ┌─────────────────────────┐                ┌────────────────────────┐
        │ Fold 6 (Termux)         │                │ kadx / ODIN (Kali)     │
        │                         │                │                        │
        │  ┌──────────────────┐   │   SSH/-R       │  ┌──────────────────┐  │
        │  │ microsocks       │◄──┤◄─ tunnel ─────│  │ proxychains4     │  │
        │  │ 127.0.0.1:9050   │   │  9050 ↔ 9050  │  │ -> 127.0.0.1:9050│  │
        │  └────────┬─────────┘   │                │  └─────────┬────────┘  │
        │           │             │                │            │           │
        │           ▼             │                │            ▼           │
        │  ┌──────────────────┐   │                │  ┌──────────────────┐  │
        │  │ phone Wi-Fi NIC  │   │                │  │ nmap, msf, etc.  │  │
        │  └────────┬─────────┘   │                │  └──────────────────┘  │
        │           │             │                │            ▲           │
        │           ▼             │   user keystrokes           │           │
        │   Target LAN           │   ◄── over SSH session ──────┘           │
        │   (192.168.1.0/24,     │                                          │
        │    coffee shop, etc.)  │                                          │
        └─────────────────────────┘                └────────────────────────┘
```

## Pieces

| Component | Where | Role |
|-----------|-------|------|
| `microsocks` | Fold 6 | SOCKS5 server on `127.0.0.1:9050`; relays incoming SOCKS connections out the phone's Wi-Fi. |
| `sshd` (Termux openssh) | Fold 6, port 8022 | Kadx connects in to copy keys, write scripts, etc. — *not* used by the pivot itself. |
| `autossh` | Fold 6 | Owns the long-lived `ssh -R` tunnel; auto-reconnects on network blips. |
| `OpenSSH server` | kadx, port 2222 | Receives the reverse tunnel from the phone. Listens on Tailscale IP + LAN IP only. Key-only auth. |
| `proxychains4` | kadx | Wraps non-SOCKS-aware tools so they route TCP through `127.0.0.1:9050`. |
| `pivot` wrapper | kadx | Per-tool entry point: uses native SOCKS for `msf`/`curl`/`sqlmap`, proxychains for `nmap`/`hydra`/etc. |
| `pivot-up.sh` | Fold 6 | Starts microsocks, finds reachable kadx target, opens autossh. |
| `scan-here` | Fold 6 | Auto-detects current LAN from `wlan0`, runs `pivot nmap` of that LAN on kadx, logs to `~/pivot-logs/`. |
| `menu` | Fold 6 | `gum`-based TUI binding the above. |

## Connection paths (in priority order)

`pivot-up.sh` tries kadx targets in this order:

1. **Tailscale IP (`100.105.140.70`)** — works anywhere if Tailscale routes are visible to Termux. The portable case.
2. **MagicDNS name (`kadx`)** — fallback for when Tailscale resolves names but bare IP routing is hidden.
3. **LAN IP (`192.168.1.165`)** — works only when the phone is on the same Wi-Fi as kadx. The at-home case.

It uses the first one that completes a TCP handshake on port 2222.

## Why this shape and not something simpler

- **Why a SOCKS proxy on the phone and not just running `nmap` in Termux?** Termux has a tiny subset of Kali's tooling. Real msfconsole / sqlmap / proper nmap with NSE scripts lives on kadx. The phone's job is to be the network presence, not to run tools.
- **Why `ssh -R` from the phone rather than `ssh -L` from kadx?** When the phone is mobile, its IP and reachability change constantly. Outbound `ssh -R` from the phone works regardless of whether the phone is behind NAT, on cellular, or on a hostile guest Wi-Fi. Inbound to the phone is fragile (see below).
- **Why is inbound to the phone not used?** Android's Tailscale VpnService and Termux's sandbox don't always cooperate — Termux can't always see Tailscale's routes. Outbound from Termux usually works; inbound to Termux often doesn't. So the architecture only depends on the direction that's reliable.

## Logs

- Every `pivot nmap` (and `scan-here`) writes to `~/pivot-logs/YYYY-MM-DD/HHMMSS-action.log` on kadx.
- `~/pivot-logs/latest.log` is a symlink to the most recent.
- Logs persist until you delete them. No automatic rotation.
