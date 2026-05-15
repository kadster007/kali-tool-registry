# Troubleshooting

## `pivot-up.sh`: "no kadx target is reachable from this phone"

`pivot-up.sh` couldn't TCP-connect to any of: Tailscale IP, MagicDNS name, LAN IP. Diagnosing in order:

1. **Are you on Wi-Fi or cellular?** Confirm `ip addr show wlan0` (or `rmnet0` for cellular) shows an IP.
2. **Is Tailscale on the phone?** Open the app — toggle should be green/connected. If you see "Not connected," tap to connect.
3. **Is the Tailscale exit node turned on?** Counterintuitively, exit-node mode makes Termux unable to reach tailnet IPs. Tailscale app → Use exit node → **None**.
4. **Toggle Tailscale off & on** in the phone app. This sometimes refreshes the routes Termux can see.
5. **Is sshd up on kadx?** From any device that can SSH to kadx (or kadx itself): `ss -tlnp | grep :2222` should show two listeners (Tailscale + LAN).

## Termux says `network unreachable` or `connection timed out` to `100.x.y.z`

Termux can't see Tailscale's routes — known Android quirk. Same fixes as above (#3, #4). If persistent, in Android Settings → Network & Internet → VPN → Tailscale → ⚙️ → **Always-on VPN: ON**. This makes Android install Tailscale's routes more aggressively for all apps.

## `proxychains` shows `[proxychains] DLL init` lines all over msfconsole

You wrapped `msfconsole` with `proxychains`. Don't — msfconsole has native SOCKS5 support. Use `pivot msf` (which sets `Proxies socks5:127.0.0.1:9050` via the resource file instead).

## Scans through the pivot are slow

SOCKS5 is per-TCP-connection. A /24 sweep on 5 ports = ~1300 sequential-ish probes. Scope tight:
- Single host or small ranges
- Few ports (top-15 instead of full /24)
- `-T4` to push timing harder (but watch out for false negatives on slow networks)
- Run host discovery natively from the phone first (`nmap -sn 192.168.x.0/24` in Termux), then proxy only the deeper scans of confirmed live hosts.

## Phone goes to sleep and the tunnel dies

Android killed Termux. Two settings to check:
1. **Settings → Apps → Termux → Battery → Unrestricted**.
2. Termux must have `termux-wake-lock` active — `pivot-up.sh` does this for you, but only while it's running.
3. Optional: install **Termux:Boot** to auto-start sshd and the tunnel on phone boot.

## `pkill autossh` doesn't kill it cleanly / it keeps respawning

That's autossh doing its job. Use:
```bash
pkill -f autossh && pkill -f "ssh.*-R.*9050"
```
…to kill both the supervisor and the underlying ssh.

## I want to push to the GitHub repo from kadx but get `Permission denied (publickey)`

Add `~/.ssh/id_ed25519_github.pub` to GitHub → Settings → SSH and GPG keys. `~/.ssh/config` on kadx already routes `github.com` through that key — once it's added to GitHub, `git push` works.
