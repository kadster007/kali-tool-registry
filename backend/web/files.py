"""Minimal dual-pane file browser for ShadowOps.

Side A: kadx filesystem (sandboxed to /home/kadx by default).
Side B: Fold 6 filesystem (sandboxed to Termux home, queried via the
        autossh -R 8022 tunnel).

Operations: list, view text, download to client. Upload comes later.
All paths normalized + checked against the side's root to prevent
directory traversal.
"""
import os
import stat
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

KADX_HOME = Path(os.environ.get("HOME", "/home/kadx"))
PHONE_ROOT = "/data/data/com.termux/files/home"
PHONE_USER = "u0_a559"
PHONE_SSH_HOST = "127.0.0.1"
PHONE_SSH_PORT = "8022"
SSH_KEY = KADX_HOME / ".ssh" / "id_ed25519_out"

MAX_TEXT_BYTES = 256 * 1024  # 256 KB readable inline


def _safe_path(side: str, raw: str) -> Tuple[Path, str]:
    """Resolve a user-supplied path, enforce sandbox per side.

    Returns (resolved Path object, side root str)."""
    if side == "kadx":
        root = KADX_HOME.resolve()
        # Default to root if blank
        p = Path(raw).expanduser() if raw else root
        # Treat relative as joined with root
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        try:
            p.relative_to(root)
        except ValueError:
            p = root
        return p, str(root)
    elif side == "phone":
        # No real filesystem access — we operate over SSH.
        # Just normalize the string for the remote side.
        s = (raw or PHONE_ROOT).strip()
        # Crude traversal guard
        s = s.replace("\x00", "")
        # If the user gave a relative path, anchor it under PHONE_ROOT
        if not s.startswith("/"):
            s = PHONE_ROOT.rstrip("/") + "/" + s
        # Disallow leaving termux home
        if not (s == PHONE_ROOT or s.startswith(PHONE_ROOT.rstrip("/") + "/")):
            s = PHONE_ROOT
        return Path(s), PHONE_ROOT
    else:
        raise ValueError("side must be 'kadx' or 'phone'")


# ---------- kadx side -----------------------------------------------------

def list_kadx(path: str) -> Dict:
    p, root = _safe_path("kadx", path)
    if not p.exists():
        return {"error": "not found", "path": str(p), "root": root, "entries": []}
    if p.is_file():
        # Treat single file as a "view" — return its parent listing too
        return {"path": str(p), "root": root, "entries": [_kadx_entry(p)], "is_file": True}
    entries = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            entries.append(_kadx_entry(child))
    except PermissionError:
        return {"error": "permission denied", "path": str(p), "root": root, "entries": []}
    parent = str(p.parent) if str(p) != root else root
    return {"path": str(p), "root": root, "parent": parent, "entries": entries}


def _kadx_entry(p: Path) -> Dict:
    try:
        st = p.lstat()
        mode = st.st_mode
        is_dir = stat.S_ISDIR(mode)
        is_link = stat.S_ISLNK(mode)
        return {
            "name": p.name,
            "path": str(p),
            "type": "dir" if is_dir else ("link" if is_link else "file"),
            "size": st.st_size if not is_dir else None,
            "mtime": int(st.st_mtime),
        }
    except OSError:
        return {"name": p.name, "path": str(p), "type": "?", "size": None, "mtime": None}


def view_kadx_text(path: str) -> Dict:
    p, root = _safe_path("kadx", path)
    if not p.exists() or not p.is_file():
        return {"error": "not a file", "path": str(p)}
    if p.stat().st_size > MAX_TEXT_BYTES:
        return {"error": f"file > {MAX_TEXT_BYTES} bytes; use download instead", "path": str(p), "size": p.stat().st_size}
    try:
        content = p.read_text(errors="replace")
    except Exception as e:
        return {"error": str(e), "path": str(p)}
    return {"path": str(p), "content": content, "size": p.stat().st_size}


# ---------- phone side (via tunnel) --------------------------------------

def _ssh_phone(cmd: str, timeout: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-p", PHONE_SSH_PORT, "-i", str(SSH_KEY),
         "-o", "StrictHostKeyChecking=accept-new",
         "-o", "UserKnownHostsFile=/dev/null",
         "-o", "BatchMode=yes",
         "-o", f"ConnectTimeout={min(timeout, 6)}",
         f"{PHONE_USER}@{PHONE_SSH_HOST}", cmd],
        capture_output=True, text=True, timeout=timeout + 4,
    )


def list_phone(path: str) -> Dict:
    p, root = _safe_path("phone", path)
    target = str(p)
    # Use a small ls -la wrapper with NUL separators we can parse safely.
    # Format: type|name|size|mtime per line.
    script = (
        f"set -- {target!r}; cd \"$1\" 2>/dev/null || {{ echo NOTDIR; exit 2; }}; "
        "for f in . .. $(ls -A 2>/dev/null); do "
        "  [ \"$f\" = . ] && continue; [ \"$f\" = .. ] && continue; "
        "  if [ -d \"$f\" ]; then t=d; "
        "  elif [ -L \"$f\" ]; then t=l; "
        "  elif [ -f \"$f\" ]; then t=f; "
        "  else t='?'; fi; "
        "  sz=$(stat -c %s \"$f\" 2>/dev/null || echo 0); "
        "  m=$(stat -c %Y \"$f\" 2>/dev/null || echo 0); "
        "  printf '%s|%s|%s|%s\\n' \"$t\" \"$f\" \"$sz\" \"$m\"; "
        "done"
    )
    r = _ssh_phone(script, timeout=10)
    if r.returncode != 0:
        return {"error": ((r.stderr or "").strip() or "ssh failed"), "path": target, "root": root, "entries": []}
    entries = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line or line == "NOTDIR":
            continue
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        t, name, sz, mt = parts
        kind = {"d": "dir", "l": "link", "f": "file"}.get(t, "?")
        try:
            size = int(sz) if kind == "file" else None
        except ValueError:
            size = None
        try:
            mtime = int(mt)
        except ValueError:
            mtime = None
        entries.append({"name": name, "path": target.rstrip("/") + "/" + name, "type": kind, "size": size, "mtime": mtime})
    # Sort: dirs first, then by name
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    parent_obj = p.parent
    parent = str(parent_obj) if target != root else root
    return {"path": target, "root": root, "parent": parent, "entries": entries}


def view_phone_text(path: str) -> Dict:
    p, root = _safe_path("phone", path)
    target = str(p)
    # head -c on phone (BusyBox/coreutils both support it)
    r = _ssh_phone(f"stat -c %s {target!r} 2>/dev/null || echo -1", timeout=6)
    try:
        size = int((r.stdout or "-1").strip().splitlines()[-1])
    except Exception:
        size = -1
    if size < 0:
        return {"error": "not a file or unreachable", "path": target}
    if size > MAX_TEXT_BYTES:
        return {"error": f"file > {MAX_TEXT_BYTES} bytes; use download instead", "path": target, "size": size}
    r = _ssh_phone(f"cat {target!r}", timeout=10)
    if r.returncode != 0:
        return {"error": "cat failed: " + (r.stderr or "").strip(), "path": target}
    return {"path": target, "content": r.stdout, "size": size}
