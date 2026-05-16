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


@app.get("/api/status_panel", response_class=HTMLResponse)
async def api_status_panel(request: Request):
    """HTMX fragment for the dashboard status panel auto-refresh."""
    return templates.TemplateResponse(request, "_status_panel.html", {
        "tunnel_up": pivot_tunnel_up(),
        "fold6_status": fold6_tailscale_status(),
        "egress_pivot": pivot_egress_ip(),
        "egress_direct": kadx_direct_ip(),
    })


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
async def tool_detail(request: Request, tool_id: str):
    tool = next((t for t in load_tools() if t.get("_id") == tool_id), None)
    if not tool:
        return HTMLResponse(f"<p>Tool {tool_id} not found.</p>", status_code=404)
    return templates.TemplateResponse(request, "tool_detail.html", {
        "tool": tool,
        "page": "tools",
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
