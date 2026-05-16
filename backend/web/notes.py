"""Personal log: timestamped text notes + optional file attachments.
Stored in /home/kadx/portable-pivot-data/notes/, outside the git repo so
they aren't accidentally committed.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

HOME = Path(os.environ.get("HOME", "/home/kadx"))
DATA_DIR = HOME / "portable-pivot-data" / "notes"
INDEX_PATH = DATA_DIR / "index.json"


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        INDEX_PATH.write_text("[]")


def _load() -> List[Dict]:
    _ensure()
    try:
        return json.loads(INDEX_PATH.read_text() or "[]")
    except json.JSONDecodeError:
        return []


def _save(notes: List[Dict]) -> None:
    INDEX_PATH.write_text(json.dumps(notes, indent=2))


def list_notes() -> List[Dict]:
    return sorted(_load(), key=lambda n: n["ts"], reverse=True)


def add(body: str, title: str = "", attachment_name: Optional[str] = None,
        attachment_bytes: Optional[bytes] = None) -> Dict:
    nid = uuid.uuid4().hex[:10]
    ts = int(time.time())
    note = {
        "id": nid,
        "ts": ts,
        "title": title.strip()[:120],
        "body": (body or "").strip()[:50000],
    }
    if attachment_bytes and attachment_name:
        safe = re.sub(r"[^A-Za-z0-9._\-]", "_", attachment_name)[:80]
        att = DATA_DIR / f"{nid}-{safe}"
        att.write_bytes(attachment_bytes[:10 * 1024 * 1024])  # 10MB cap
        note["attachment"] = att.name
        note["attachment_size"] = len(attachment_bytes)
    notes = _load()
    notes.append(note)
    _save(notes)
    return note


def delete(nid: str) -> bool:
    notes = _load()
    new = [n for n in notes if n["id"] != nid]
    if len(new) == len(notes):
        return False
    # delete attachment if any
    target = next((n for n in notes if n["id"] == nid), None)
    if target and target.get("attachment"):
        try:
            (DATA_DIR / target["attachment"]).unlink()
        except FileNotFoundError:
            pass
    _save(new)
    return True


def get_attachment_path(nid: str) -> Optional[Path]:
    notes = _load()
    note = next((n for n in notes if n["id"] == nid), None)
    if not note or not note.get("attachment"):
        return None
    p = DATA_DIR / note["attachment"]
    return p if p.exists() else None
