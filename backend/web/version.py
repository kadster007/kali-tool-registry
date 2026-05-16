"""Project version + build info, surfaced in the UI footer."""
import subprocess
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_VERSION = "0.5.0"   # bump on user-visible changes


def info() -> Dict:
    """Return version dict for templates / /api/version."""
    git_sha = "?"
    git_branch = "?"
    git_dirty = False
    try:
        git_sha = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "?"
        git_branch = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "?"
        status = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        git_dirty = bool(status)
    except Exception:
        pass
    return {
        "version": APP_VERSION,
        "git_sha": git_sha,
        "git_branch": git_branch,
        "git_dirty": git_dirty,
        "display": f"v{APP_VERSION} · {git_branch}@{git_sha}{'+' if git_dirty else ''}",
    }
