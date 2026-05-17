"""
ShadowOps web UI — FastAPI app served from kadx, accessed via Tailscale.

Endpoints (HTML routes return Jinja templates; HTMX swaps fragments where useful):
  GET  /                       Dashboard (pivot status, recent scans)
  GET  /api/status             JSON pivot status (used by dashboard auto-refresh)
  GET  /scan                   Scan form
  POST /scan                   Start a scan, returns scan-run page with job id
  WS   /ws/scan/{job_id}       Live output stream of a running scan
  GET  /tools                  Browse tools/*.json registry
  GET  /tools/{tool_id}        Tool detail (flags, presets)
  GET  /logs                   Browse ~/pivot-logs
  GET  /logs/view              View a specific log (?path=)
"""

import asyncio
import json
import os
import re
import shlex
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# local helpers
import phone as phone_mod
import phases as phases_mod
import terminal as terminal_mod
import notes as notes_mod
import version as version_mod
import scan as scan_mod
import files as files_mod

# ---- paths -----------------------------------------------------------------
HOME = Path(os.environ.get("HOME", "/home/kadx"))
REPO_ROOT = Path(__file__).resolve().parents[2]          # .../portable-pivot
TOOLS_DIR = REPO_ROOT / "tools"
LOGS_DIR = HOME / "pivot-logs"
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
PIVOT_BIN = HOME / ".local" / "bin" / "pivot"
SOCKS_PORT = 9050

LOGS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ShadowOps")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _datetimeformat(value):
    from datetime import datetime
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


templates.env.filters["datetimeformat"] = _datetimeformat
templates.env.globals["app_version"] = version_mod.info

# ---- helpers ---------------------------------------------------------------

def pivot_tunnel_up() -> bool:
    """Return True if something is listening on 127.0.0.1:9050 (the ssh -R)."""
    try:
        out = subprocess.run(
            ["ss", "-tln"], capture_output=True, text=True, timeout=3
        ).stdout
        return bool(re.search(r"127\.0\.0\.1:%d\s" % SOCKS_PORT, out))
    except Exception:
        return False


def pivot_egress_ip() -> Optional[str]:
    """Curl --socks5 through the pivot to discover the phone's WAN IP."""
    if not pivot_tunnel_up():
        return None
    try:
        r = subprocess.run(
            ["curl", "-sS", "--max-time", "5", "--socks5",
             f"127.0.0.1:{SOCKS_PORT}", "https://ifconfig.me"],
            capture_output=True, text=True, timeout=8,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def kadx_direct_ip() -> Optional[str]:
    try:
        r = subprocess.run(
            ["curl", "-sS", "--max-time", "5", "https://ifconfig.me"],
            capture_output=True, text=True, timeout=8,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def fold6_tailscale_status() -> Optional[str]:
    try:
        out = subprocess.run(
            ["tailscale", "status"], capture_output=True, text=True, timeout=4
        ).stdout
        for line in out.splitlines():
            if "fold6" in line.lower():
                # Return the trailing state column
                return " ".join(line.split())
    except Exception:
        pass
    return None


def recent_scans(limit: int = 8) -> List[Dict]:
    """List recent scan logs, newest first."""
    if not LOGS_DIR.exists():
        return []
    files = []
    for p in LOGS_DIR.glob("*/*.log"):
        try:
            stat = p.stat()
            files.append({
                "path": str(p),
                "rel": str(p.relative_to(HOME)),
                "name": p.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "mtime_ts": stat.st_mtime,
            })
        except FileNotFoundError:
            continue
    files.sort(key=lambda x: x["mtime_ts"], reverse=True)
    return files[:limit]


def load_tools() -> List[Dict]:
    """Load tools/*.json (one tool per file)."""
    if not TOOLS_DIR.exists():
        return []
    tools = []
    for p in sorted(TOOLS_DIR.glob("*.json")):
        if p.name == "registry.json":
            continue
        try:
            data = json.loads(p.read_text())
            data["_file"] = p.name
            data["_id"] = p.stem
            tools.append(data)
        except Exception as e:
            tools.append({"_file": p.name, "_id": p.stem, "_error": str(e)})
    return tools


def load_registry() -> Dict:
    p = TOOLS_DIR / "registry.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


# ---- in-memory job tracker -------------------------------------------------
JOBS: Dict[str, Dict] = {}        # job_id -> {proc, log_path, cmd, started_at, ended_at}


def safe_target(s: str) -> str:
    """Allow only chars valid for hosts/CIDR/IPs."""
    return re.sub(r"[^A-Za-z0-9._\-/:,]", "", s)[:128]


def safe_ports(s: str) -> str:
    return re.sub(r"[^0-9,\-]", "", s)[:256]


# ---- routes ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "tunnel_up": pivot_tunnel_up(),
        "fold6_status": fold6_tailscale_status(),
        "egress_pivot": None,           # filled on demand by /api/status
        "egress_direct": None,
        "recent": recent_scans(8),
        "page": "dashboard",
    })


@app.get("/api/status")
async def api_status():
    return {
        "tunnel_up": pivot_tunnel_up(),
        "fold6_status": fold6_tailscale_status(),
        "egress_pivot": pivot_egress_ip(),
        "egress_direct": kadx_direct_ip(),
        "recent_count": len(recent_scans(50)),
        "ts": int(time.time()),
    }


@app.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request):
    return templates.TemplateResponse(request, "scan.html", {
        "tunnel_up": pivot_tunnel_up(),
        "page": "scan",
    })


@app.post("/scan", response_class=HTMLResponse)
async def scan_start(
    request: Request,
    target: str = Form(...),
    ports: str = Form("22,80,443,445,3389,8080,8443"),
):
    if not pivot_tunnel_up():
        return HTMLResponse(
            "<p style='color:#f88'>Pivot tunnel is DOWN. Start it from the phone first.</p>",
            status_code=400,
        )

    target = safe_target(target)
    ports = safe_ports(ports)
    if not target:
        return HTMLResponse("<p style='color:#f88'>target required</p>", status_code=400)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    date_dir = LOGS_DIR / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    safe_t = target.replace("/", "_")
    log_path = date_dir / f"{ts}-web-nmap-{safe_t}.log"
    job_id = uuid.uuid4().hex[:8]

    cmd = [str(PIVOT_BIN), "nmap", "-T4", "-p", ports, target]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    JOBS[job_id] = {
        "proc": proc,
        "log_path": log_path,
        "cmd": " ".join(shlex.quote(c) for c in cmd),
        "started_at": time.time(),
        "ended_at": None,
        "exit_code": None,
    }
    # Touch latest symlink immediately
    latest = LOGS_DIR / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(log_path)
    except Exception:
        pass

    return templates.TemplateResponse(request, "scan_run.html", {
        "job_id": job_id,
        "cmd": JOBS[job_id]["cmd"],
        "log_rel": str(log_path.relative_to(HOME)),
        "page": "scan",
    })


@app.websocket("/ws/scan/{job_id}")
async def ws_scan(ws: WebSocket, job_id: str):
    await ws.accept()
    job = JOBS.get(job_id)
    if not job:
        await ws.send_text("[error] unknown job\n")
        await ws.close()
        return
    proc = job["proc"]
    log_path: Path = job["log_path"]

    try:
        with log_path.open("ab") as logf:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                logf.write(line)
                logf.flush()
                try:
                    await ws.send_text(line.decode("utf-8", "replace"))
                except WebSocketDisconnect:
                    break
        await proc.wait()
        job["ended_at"] = time.time()
        job["exit_code"] = proc.returncode
        try:
            await ws.send_text(f"\n[done] exit={proc.returncode}\n")
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/tools", response_class=HTMLResponse)
async def tools_list(request: Request):
    return templates.TemplateResponse(request, "tools.html", {
        "tools": load_tools(),
        "registry": load_registry(),
        "page": "tools",
    })


@app.get("/tools/{tool_id}", response_class=HTMLResponse)
async def tool_detail(request: Request, tool_id: str, target: str = ""):
    tool = next((t for t in load_tools() if t.get("_id") == tool_id), None)
    if not tool:
        return HTMLResponse(f"<p>Tool {tool_id} not found.</p>", status_code=404)
    # Provide known hosts for the target picker
    known = []
    try:
        known = [{"ip": h["ip"], "hostnames": h.get("hostnames") or []}
                 for h in scan_mod.hosts_sorted() if h.get("state") == "up"]
    except Exception:
        pass
    return templates.TemplateResponse(request, "tool_detail.html", {
        "tool": tool,
        "page": "tools",
        "target_default": target,
        "known_hosts": known,
    })


@app.get("/logs", response_class=HTMLResponse)
async def logs_list(request: Request):
    return templates.TemplateResponse(request, "logs.html", {
        "logs": recent_scans(100),
        "page": "logs",
    })


@app.get("/logs/view", response_class=HTMLResponse)
async def log_view(request: Request, path: str):
    # Containment: log must be under LOGS_DIR
    try:
        p = Path(path).resolve()
        p.relative_to(LOGS_DIR.resolve())
    except (ValueError, RuntimeError):
        return HTMLResponse("<p>refusing to serve path outside ~/pivot-logs</p>", status_code=400)
    if not p.exists() or not p.is_file():
        return HTMLResponse(f"<p>not found: {p}</p>", status_code=404)
    content = p.read_text(errors="replace")
    return templates.TemplateResponse(request, "log_view.html", {
        "log_path": str(p.relative_to(HOME)),
        "log_content": content,
        "page": "logs",
    })


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"


@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page(request: Request):
    """Full-screen terminal page (no sidebars). Same xterm.js + pty backend."""
    return templates.TemplateResponse(request, "terminal.html", {"page": "terminal"})


@app.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    return templates.TemplateResponse(request, "files.html", {
        "page": "files",
        "phone_root": files_mod.PHONE_ROOT,
    })


@app.get("/api/files/{side}")
async def api_files_list(side: str, path: str = ""):
    if side == "kadx":
        return files_mod.list_kadx(path or str(files_mod.KADX_HOME))
    elif side == "phone":
        return files_mod.list_phone(path or files_mod.PHONE_ROOT)
    return JSONResponse({"error": "unknown side"}, status_code=400)


@app.get("/api/files/{side}/view")
async def api_files_view(side: str, path: str):
    if side == "kadx":
        return files_mod.view_kadx_text(path)
    elif side == "phone":
        return files_mod.view_phone_text(path)
    return JSONResponse({"error": "unknown side"}, status_code=400)


@app.get("/api/files/{side}/download")
async def api_files_download(side: str, path: str):
    from fastapi.responses import FileResponse, StreamingResponse
    if side == "kadx":
        p, root = files_mod._safe_path("kadx", path)
        if not p.exists() or not p.is_file():
            return PlainTextResponse("not a file", status_code=404)
        return FileResponse(p, filename=p.name)
    elif side == "phone":
        p, _root = files_mod._safe_path("phone", path)
        target = str(p)
        # Stream the file by SSH-cat'ing it back
        proc = subprocess.Popen(
            ["ssh", "-p", files_mod.PHONE_SSH_PORT, "-i", str(files_mod.SSH_KEY),
             "-o", "StrictHostKeyChecking=accept-new",
             "-o", "UserKnownHostsFile=/dev/null",
             "-o", "BatchMode=yes",
             f"{files_mod.PHONE_USER}@{files_mod.PHONE_SSH_HOST}", f"cat {target!r}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        def gen():
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    proc.wait()
                    return
                yield chunk
        from urllib.parse import quote
        return StreamingResponse(gen(), media_type="application/octet-stream",
                                 headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(p.name)}"})
    return PlainTextResponse("unknown side", status_code=400)


@app.get("/api/right_host_panel", response_class=HTMLResponse)
async def api_right_host_panel(request: Request):
    """Right sidebar — current scan only (most recent XML file)."""
    try:
        scan = scan_mod.latest_scan()
        return templates.TemplateResponse(request, "_right_host_panel.html", {
            "scan": scan,
        })
    except Exception as e:
        return templates.TemplateResponse(request, "_error_card.html",
            {"title": "Current scan", "msg": str(e), "retry": "/api/right_host_panel"})


# --- new: phone state & pivot control endpoints --------------------------

@app.get("/api/phone_info")
async def api_phone_info(force: int = 0):
    return phone_mod.phone_info(force=bool(force))


@app.get("/api/left_panel", response_class=HTMLResponse)
async def api_left_panel(request: Request):
    info = phone_mod.phone_info()
    return templates.TemplateResponse(request, "_left_panel.html", {
        "tunnel_up": pivot_tunnel_up(),
        "phone": info,
        "egress_pivot": pivot_egress_ip() if pivot_tunnel_up() else None,
        "egress_direct": kadx_direct_ip(),
    })


@app.get("/api/right_panel", response_class=HTMLResponse)
async def api_right_panel(request: Request):
    return templates.TemplateResponse(request, "_right_panel.html", {
        "recent": recent_scans(15),
    })


@app.post("/api/pivot/release")
async def api_pivot_release():
    return phone_mod.pivot_release()


@app.post("/api/pivot/reset")
async def api_pivot_reset():
    return phone_mod.pivot_reset()


@app.post("/api/pivot/restart")
async def api_pivot_restart():
    return phone_mod.pivot_restart_full()


@app.post("/api/pivot/start")
async def api_pivot_start():
    """Auto-start: SSH to phone and bring up the pivot. Returns the start command
    as a fallback if we can't reach the phone."""
    if phone_mod.can_ssh_phone():
        return phone_mod.pivot_reset()
    return {
        "ok": False,
        "fallback_command": "~/portable-pivot/frontend/pivot-up.sh",
        "output": "Can't SSH to phone. Run the command on the phone in Termux.",
    }


@app.get("/api/pivot/start_command", response_class=PlainTextResponse)
async def api_pivot_start_command():
    return "~/portable-pivot/frontend/pivot-up.sh"


# --- phases panel + terminal --------------------------------------------

@app.get("/api/phases_panel", response_class=HTMLResponse)
async def api_phases_panel(request: Request):
    try:
        phases = phases_mod.phases_with_tools(TOOLS_DIR)
    except Exception as e:
        return templates.TemplateResponse(request, "_error_card.html",
            {"title": "Phases", "msg": f"failed to load: {e}", "retry": "/api/phases_panel"})
    return templates.TemplateResponse(request, "_phases.html", {"phases": phases})


@app.get("/api/pivot_panel", response_class=HTMLResponse)
async def api_pivot_panel(request: Request):
    # Back-compat alias for older clients; the new consolidated panel is /api/status_panel
    return await api_status_panel(request)


@app.get("/api/status_panel", response_class=HTMLResponse)
async def api_status_panel(request: Request):
    """Consolidated Pivot + Fold 6 panel."""
    try:
        info = phone_mod.phone_info(force=False)
        return templates.TemplateResponse(request, "_status_panel.html", {
            "tunnel_up": pivot_tunnel_up(),
            "phone": info,
        })
    except Exception as e:
        return templates.TemplateResponse(request, "_error_card.html",
            {"title": "Status", "msg": str(e), "retry": "/api/status_panel"})


@app.get("/api/header_status", response_class=HTMLResponse)
async def api_header_status(request: Request):
    """Tiny status indicator for the global header."""
    try:
        info = phone_mod.phone_info(force=False)
    except Exception:
        info = {"reachable": False, "raw_error": "fetch failed"}
    return templates.TemplateResponse(request, "_header_status.html", {
        "tunnel_up": pivot_tunnel_up(),
        "phone": info,
    })


@app.get("/api/diagnostic", response_class=HTMLResponse)
async def api_diagnostic(request: Request):
    """Full-stack pivot health check, returns a small HTML fragment."""
    import socket
    results = []
    def step(name, ok, detail=""):
        results.append({"name": name, "ok": ok, "detail": detail})

    # 1. SOCKS tunnel listener on kadx
    socks_up = pivot_tunnel_up()
    step("SOCKS tunnel (kadx:9050)", socks_up,
         "listener present" if socks_up else "no -R 9050 from phone")

    # 2. Phone-control tunnel listener on kadx
    phone_ssh_up = False
    try:
        with socket.create_connection(("127.0.0.1", 8022), timeout=2):
            phone_ssh_up = True
    except OSError:
        pass
    step("Phone-control tunnel (kadx:8022)", phone_ssh_up,
         "listener present — phone reachable via tunnel" if phone_ssh_up
         else "no -R 8022 — restart pivot on phone to enable (needs new pivot-up.sh)")

    # 3. SSH through tunnel
    ssh_ok = phone_mod.can_ssh_phone() if phone_ssh_up else False
    step("SSH kadx -> 127.0.0.1:8022 (phone sshd)", ssh_ok,
         "auth + shell ok" if ssh_ok else ("can't connect" if not phone_ssh_up else "auth failed?"))

    # 4. termux-wifi-connectioninfo via tunnel
    wifi_ok = False
    wifi_detail = ""
    if ssh_ok:
        info = phone_mod.phone_info(force=True)
        wifi_ok = info.get("reachable") and info.get("ip") is not None
        if wifi_ok:
            wifi_detail = f"{info.get('connection')} · {info.get('ssid')} · {info.get('ip')}"
        else:
            wifi_detail = info.get("raw_error", "unknown")
    step("Phone network info", wifi_ok, wifi_detail)

    # 5. Curl through SOCKS pivot
    pivot_egress = None
    if socks_up:
        pivot_egress = pivot_egress_ip()
    step("Pivot egress (curl via SOCKS5)", bool(pivot_egress),
         pivot_egress or "no response")

    return templates.TemplateResponse(request, "_diagnostic.html", {"results": results})


@app.get("/api/fold6_panel", response_class=HTMLResponse)
async def api_fold6_panel(request: Request, force: int = 1):
    # Back-compat alias: returns the consolidated _status_panel with a forced phone-info refresh.
    try:
        info = phone_mod.phone_info(force=bool(force))
        return templates.TemplateResponse(request, "_status_panel.html", {
            "tunnel_up": pivot_tunnel_up(),
            "phone": info,
        })
    except Exception as e:
        return templates.TemplateResponse(request, "_error_card.html",
            {"title": "Status", "msg": str(e), "retry": "/api/status_panel"})


@app.websocket("/ws/terminal")
async def ws_terminal_endpoint(ws: WebSocket, cmd: str = "local"):
    await terminal_mod.terminal_websocket(ws, cmd)


# --- version + updates --------------------------------------------------

@app.get("/api/version")
async def api_version():
    return version_mod.info()


def _bg_restart_self():
    import threading
    def _r():
        time.sleep(1.5)
        os.system("systemctl --user restart shadowops-web.service")
    threading.Thread(target=_r, daemon=True).start()


@app.post("/api/update/kadx")
async def api_update_kadx():
    """git pull on kadx + restart the web service (in the background)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
        )
        ok = r.returncode == 0
        out = (r.stdout or "") + (r.stderr or "")
        if ok:
            _bg_restart_self()
            out += "\n[restart] shadowops-web restarting in ~2s"
        return {"ok": ok, "output": out.strip()[-2000:]}
    except Exception as e:
        return {"ok": False, "output": str(e)}


@app.post("/api/update/phone")
async def api_update_phone():
    """git pull on phone via the tunnel. Optionally restart pivot if user wants
    to (we don't auto-restart because that would kill our own SSH path)."""
    r = phone_mod._ssh_phone(
        "cd ~/portable-pivot 2>/dev/null && git pull --ff-only 2>&1 || echo 'no repo at ~/portable-pivot'",
        timeout=30,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return {"ok": r.returncode == 0, "output": out.strip()[-2000:]}


@app.post("/api/pivot/kill_autossh")
async def api_pivot_kill_autossh():
    """Kill the autossh process on the phone (forces a clean stop, no auto-reconnect)."""
    r = phone_mod._ssh_phone(
        "pkill -f 'autossh.*-R.*9050' 2>/dev/null && echo killed-autossh; "
        "pkill -x microsocks 2>/dev/null && echo killed-microsocks; "
        "echo done",
        timeout=10,
    )
    return {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}


# --- personal notes -----------------------------------------------------

@app.get("/notes", response_class=HTMLResponse)
async def notes_page(request: Request):
    return templates.TemplateResponse(request, "notes.html", {
        "notes": notes_mod.list_notes(),
        "page": "notes",
    })


@app.post("/api/notes")
async def api_notes_add(request: Request):
    form = await request.form()
    title = form.get("title", "")
    body = form.get("body", "")
    file = form.get("attachment")
    att_name = None
    att_bytes = None
    # UploadFile vs str
    if file and hasattr(file, "filename") and file.filename:
        att_name = file.filename
        att_bytes = await file.read()
    notes_mod.add(body=body, title=title, attachment_name=att_name, attachment_bytes=att_bytes)
    return RedirectResponse(url="/notes", status_code=303)


@app.post("/api/notes/{nid}/delete")
async def api_notes_delete(nid: str):
    ok = notes_mod.delete(nid)
    return RedirectResponse(url="/notes", status_code=303)


# --- structured hosts (Phase 2 / 3) ------------------------------------

@app.get("/hosts", response_class=HTMLResponse)
async def hosts_list(request: Request, scan: str = "latest"):
    """Hosts page. Default: latest scan only (so new scans dominate the view).
    Override with ?scan=all (aggregate) or ?scan=<filename> (specific scan)."""
    scans = scan_mod.scan_list()
    if scan == "all":
        hosts = scan_mod.hosts_sorted()
        active_label = "Aggregate of all scans"
        active_file = None
    elif scan == "latest" or not scan:
        s = scan_mod.latest_scan()
        hosts = scan_mod.hosts_from_scan(s)
        active_label = "Latest scan"
        active_file = s.get("file") if s else None
    else:
        # Allow either basename or absolute path
        target = next((x for x in scans if x["name"] == scan or x["file"] == scan), None)
        s = scan_mod.scan_by_file(target["file"]) if target else None
        hosts = scan_mod.hosts_from_scan(s)
        active_label = target["name"] if target else "(not found)"
        active_file = target["file"] if target else None
    return templates.TemplateResponse(request, "hosts.html", {
        "hosts": hosts,
        "page": "hosts",
        "scans": scans,
        "active_scan": scan,
        "active_label": active_label,
        "active_file": active_file,
    })


@app.get("/hosts/{ip}", response_class=HTMLResponse)
async def host_detail(request: Request, ip: str):
    h = scan_mod.host_by_ip(ip)
    if not h:
        return HTMLResponse(f"<p>Host <code>{ip}</code> not in any scan yet. Run a scan first.</p>", status_code=404)
    return templates.TemplateResponse(request, "host_detail.html", {
        "host": h,
        "all_tools": load_tools(),
        "page": "hosts",
    })


@app.get("/api/phase_summary/{phase_id}", response_class=HTMLResponse)
async def api_phase_summary(request: Request, phase_id: int):
    """Tiny summary fragment for the sidebar phase header."""
    hosts = scan_mod.hosts_sorted()
    open_ports = sum(1 for h in hosts for p in h["ports"] if p.get("state") == "open")
    hosts_up = sum(1 for h in hosts if h.get("state") == "up")
    vuln_hosts = sum(1 for h in hosts if any(
        s.get("id", "").startswith("vuln") or "vulners" in (s.get("id") or "")
        for s in h.get("host_scripts") or []
    ) or any(
        any("vulner" in (sc.get("id") or "") or "vuln" in (sc.get("id") or "")
            for sc in (p.get("scripts") or []))
        for p in h["ports"]
    ))
    return templates.TemplateResponse(request, "_phase_summary.html", {
        "phase_id": phase_id,
        "hosts_up": hosts_up,
        "open_ports": open_ports,
        "vuln_hosts": vuln_hosts,
        "total_hosts": len(hosts),
    })


@app.get("/notes/attachment/{nid}")
async def notes_attachment(nid: str):
    p = notes_mod.get_attachment_path(nid)
    if not p:
        return PlainTextResponse("not found", status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(p)
