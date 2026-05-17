# Future ideas / parking lot

Things considered but deferred. Save for later, don't act now.

---

## TermuxHub integration (parked 2026-05-15)

`kadster007/TermuxHub` (fork of `maazm7d/TermuxHub`, 244★) — Kotlin/Android app that indexes Termux tools from a JSON metadata file.

**Possible integrations (future):**
1. **As discovery surface** — derive a `metadata.json` (TermuxHub-format) from our richer `tools/*.json`, point a TermuxHub instance at our repo, get a native Android tool browser for free.
2. **Fork TermuxHub into a native ShadowOps client** — replace "install in Termux" actions with "execute via SSH to kadx through pivot."
3. **Borrow UI patterns** but build smaller (current direction).

Decision: option 3 (web UI on kadx). Revisit TermuxHub if a native Android client becomes attractive.

---

## nmapwebui integration (parked 2026-05-16)

`kadster007/nmapwebui` (fork of `sphinxid/nmapwebui`) — Go web wrapper for nmap with templates / Docker. ~13★ upstream.

**What it does:**
- Go binary serving a web UI, lets users configure nmap scans via forms
- Saves results, supports scheduling
- Self-contained Docker deploy

**Why it's interesting for ShadowOps:**
- Comparable surface to our `/scan` page + `/hosts` viewer
- Its form-builder UI for nmap options is more complete than ours
- Its scan history + scheduling features are things we don't have

**Why we're not adopting it directly:**
- Written in Go; ShadowOps is Python/FastAPI. Mixing stacks is overhead.
- It runs nmap locally without our pivot wrapper, so traffic would exit
  via kadx's network instead of the phone's — defeats the architecture.
- Two web UIs is one too many.

**Possible directions (future):**
1. **Steal its form-builder design** — flag groups, presets, output format toggles — and reimplement in our `/scan` page as a richer form (we currently have target + ports).
2. **Mine its option metadata** — if it ships a structured catalog of nmap flags, fold that into our `tools/nmap.json` so the per-flag UI gets more capable.
3. **Run it side-by-side in a tab** — `tailscale serve` it on a different port, link from our nav. Doesn't pivot, but gives us a richer nmap UI for local scans.

Decision: leave parked. The /hosts + per-host detail pages cover the
"see the results" half. If we want a richer "configure the scan" form,
that's a separate effort and we'd build it natively rather than fork
a Go app.

---

## Pi Zero 2 W as wireless-recon node (parked 2026-05-17)

Phase 1 wireless attacks (aircrack-ng, kismet, wifite, hcxdumptool) need
a USB Wi-Fi adapter in monitor mode + physical RF proximity. Android
phones can't deliver this (chipset/driver locked).

**Right slot for the Pi:** drop the Pi at the target site with a
monitor-capable adapter, advertise its subnet via `tailscale set
--advertise-routes=...`, then kadx tunnels through it for wireless
recon. The Fold 6 stays out of the picture for this phase entirely.

Adapters worth pairing with a Pi Zero 2W:
- Alfa AWUS036ACH (ac dual-band)
- Panda PAU09 (cheap, reliable for 2.4GHz)
- Atheros AR9271 dongles (single-band, well-supported)

Build steps when we decide to do this:
- Flash Kali Linux ARM (Pi Zero 2W version)
- Install Tailscale, join tailnet
- `sudo tailscale set --advertise-routes=<target_subnet>/24 --advertise-exit-node`
- Plug in monitor-capable USB Wi-Fi, verify `airmon-ng check`
- From kadx: `pivot raw airodump-ng wlan1mon` (or run directly on Pi)

Sibling concept of the Fold 6 pivot, not a replacement.

---

## nmap-viewer (parked 2026-05-15, see ShadowOps Phase 2)

`kadster007/nmap-viewer` (fork of `psyray/nmap-viewer`) — JavaScript SPA
that renders nmap XML files in a browser.

We already built equivalent functionality in `backend/web/scan.py` +
`/hosts` + `/hosts/{ip}` pages. nmap-viewer can stay as a parking-lot
reference for any UI polish we want to borrow.
