# ShadowOps — Mobile-First Pentest Platform

ShadowOps is a mobile-first penetration testing platform. A Samsung Fold 6 (or any Termux-capable Android) acts as the **portable field agent**; a Kali workstation (kadx / ODIN) acts as the **remote execution engine**; they're stitched together by a SOCKS5 pivot over SSH/Tailscale. You drive the workstation from your phone; the workstation runs the heavy tools; their TCP traffic exits through whichever Wi-Fi the phone is currently on.

This repo is the successor to **FieldOps**, which described the right concept (tool registry + playbooks + remote backend) but didn't solve the *transport* problem — how the field agent actually reaches a target LAN. **ShadowOps adds that missing layer** as a working, reproducible base. The FieldOps tool registry survives intact under [`tools/`](tools/).

## How it fits together

```
┌─────────────────────────┐                ┌────────────────────────┐
│ Fold 6 (Termux)         │   ssh -R       │ kadx / ODIN (Kali)     │
│  microsocks ─── tunnel ─┼────────────────┼──→ 127.0.0.1:9050      │
│       ▲       9050↔9050 │  via Tailscale │           │            │
│       │                 │   or home LAN  │           ▼            │
│   target LAN exits  ──→ │                │   pivot wrapper       │
│   phone's Wi-Fi NIC     │                │   ↳ nmap / msf /     │
│                         │ ←─ keystrokes  │     sqlmap / hydra    │
│                         │   over SSH     │     via SOCKS5        │
└─────────────────────────┘                └────────────────────────┘
```

- **Tools** run on kadx (real Kali, real tooling, lots of RAM/disk).
- **Network exit** is the phone (so probes hit whatever network you're physically on).
- **You** type commands on the phone, see results on the phone, but everything executes on kadx.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the deeper version.

## Repo layout

```
.
├── README.md                ← this file
├── backend/                 ← lives on kadx (the execution engine)
│   ├── openssh-setup.sh     ← OpenSSH hardened, key-only, tailnet+LAN bound
│   ├── openssh-add-lan.sh   ← add LAN listener (at-home fallback)
│   ├── openssh-rollback.sh
│   ├── tailscale-setup.sh
│   ├── pivot-status.sh      ← health check
│   └── pivot/
│       ├── pivot            ← multi-tool wrapper (msf, nmap, curl, sqlmap, hydra, …)
│       └── msf.rc           ← msfconsole resource with Proxies preset
├── frontend/                ← lives on the Fold 6 (Termux)
│   ├── pivot-up.sh          ← autossh + Tailscale/MagicDNS/LAN fallback
│   ├── scan-here            ← auto-detect current Wi-Fi LAN, scan via pivot
│   ├── menu                 ← gum-based TUI tying it all together
│   └── widgets/             ← Termux:Widget one-tap shortcuts
├── tools/                   ← FieldOps tool registry (preserved)
│   ├── registry.json        ← master index + playbooks
│   ├── nmap.json
│   ├── masscan.json
│   ├── arp-scan.json
│   ├── netdiscover.json
│   ├── fping.json
│   ├── nbtscan.json
│   ├── smbmap.json
│   ├── hydra.json
│   └── hping3.json
└── docs/
    ├── ARCHITECTURE.md
    └── TROUBLESHOOTING.md
```

## What each part is for

### `tools/` — tool registry (from FieldOps)

One JSON per Kali tool with flags/options (types, descriptions, examples), preset commands, gotchas, and example invocations. `registry.json` is the master index with categories and **playbooks** — automated multi-step workflows that chain tools together, e.g.:

| Playbook | Steps | What it finds |
|----------|-------|---------------|
| Full LAN Discovery | ARP → masscan → nmap → SMB check → NetBIOS | All hosts, ports, services, shares, OS |
| Quick Host Map | ARP sweep only | Live hosts + MAC/vendor in <10s |
| SMB Audit | nmap 445 → smbmap → enum4linux | All Windows shares and users |

A playbook saves results to a **Target Profile** (JSON), and each step's output feeds the next.

### `backend/pivot/pivot` — the wrapper

```
pivot status                # tunnel + egress health
pivot up                    # quick yes/no on tunnel
pivot msf [args]            # msfconsole with Proxies preset via msf.rc
pivot nmap <target> [args]  # auto -sT -Pn; SOCKS-safe defaults
pivot curl [args]           # native --socks5
pivot sqlmap [args]         # native --proxy=socks5://
pivot hydra [args]          # via proxychains4
pivot shell                 # sub-shell where proxychains is default
pivot raw <cmd> [args]      # any tool via proxychains4
```

It picks **native SOCKS5** where the tool supports it (`msf`, `curl`, `sqlmap`) and falls back to **proxychains4** for tools that don't (`nmap`, `hydra`).

### `frontend/menu` — gum-based TUI on the phone

```
● Pivot UP — tunnel via 100.105.140.70
  Phone microsocks: running

  > Start pivot (open kadx shell)
    Scan current Wi-Fi network
    Scan specific host/CIDR
    View recent logs
    Pivot status (detail)
    Stop pivot
    Quit
```

## Quick start

### On `kadx` (one-time)

```bash
git clone git@github.com:kadster007/kali-tool-registry.git
cd kali-tool-registry
sudo bash backend/openssh-setup.sh         # OpenSSH on :2222, key-only, tailnet
sudo bash backend/openssh-add-lan.sh       # add LAN listener (at-home fallback)
ln -sf "$PWD/backend/pivot/pivot" ~/.local/bin/pivot
ln -sf "$PWD/backend/pivot-status.sh" ~/pivot-status.sh
```

### On the Fold 6 (Termux), one-time

```bash
pkg install -y git openssh microsocks gum autossh termux-api
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub                  # add this to kadx's authorized_keys
git clone git@github.com:kadster007/kali-tool-registry.git ~/portable-pivot
cd ~/portable-pivot
chmod +x frontend/*.sh frontend/scan-here frontend/menu frontend/widgets/*
mkdir -p ~/.shortcuts && cp -f frontend/widgets/* ~/.shortcuts/ && chmod +x ~/.shortcuts/*
```

Install the Android apps **Termux:API** and **Termux:Widget** from F-Droid.

### Daily use

- Tap **menu** widget on phone home screen → `gum` TUI appears.
- `Start pivot` → autossh tunnel + microsocks come up, kadx shell drops in.
- `Scan current Wi-Fi network` → auto-detects the LAN you're on, runs `nmap` via the pivot on kadx, log goes to `~/pivot-logs/`.

## Limitations

- **SOCKS5 = TCP only.** No UDP scans, no ICMP/ping, no raw sockets via the pivot. `pivot nmap` auto-uses `-sT -Pn`; `-sS`/`-sU` won't traverse.
- **Termux ↔ Tailscale on Android is fragile.** Tailscale's VPN routes sometimes aren't visible to Termux after network changes. Toggle exit-node off in the app; or toggle Tailscale itself off/on. See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
- **Battery.** Settings → Apps → Termux → Battery → Unrestricted is mandatory. `termux-wake-lock` (called by `pivot-up.sh`) is helpful but not absolute.

## Acknowledgements

ShadowOps grew out of **FieldOps** (the original tool-registry-and-playbooks concept). FieldOps remains in the repo history; the registry under `tools/` is its direct descendant.
