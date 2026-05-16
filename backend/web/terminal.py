"""Minimal pty-backed WebSocket terminal for ShadowOps.

Spawns a shell (or any command) attached to a pty, bridges stdin/stdout
through a WebSocket. xterm.js on the client side does the rendering.

Two modes supported via query param:
  ?cmd=local   -> /bin/bash on kadx (default)
  ?cmd=phone   -> ssh to the Fold 6 (uses ~/.ssh/id_ed25519_out)
"""
import asyncio
import fcntl
import json
import os
import pty
import shlex
import signal
import struct
import termios
from pathlib import Path
from typing import List

from fastapi import WebSocket, WebSocketDisconnect

HOME = Path(os.environ.get("HOME", "/home/kadx"))
PHONE_KEY = HOME / ".ssh" / "id_ed25519_out"
PHONE_USER = "u0_a559"
PHONE_PORT = "8022"
PHONE_TARGETS = ["192.168.1.197", "100.101.229.113"]


def _build_argv(cmd: str) -> List[str]:
    cmd = (cmd or "local").lower()
    if cmd == "phone":
        # Find a reachable target by quick probe
        import socket
        chosen = None
        for t in PHONE_TARGETS:
            try:
                with socket.create_connection((t, int(PHONE_PORT)), timeout=3):
                    chosen = t
                    break
            except OSError:
                continue
        if not chosen:
            # Return a shell that announces the failure to xterm
            return ["/bin/sh", "-c", "echo 'phone unreachable on any known address'; exec /bin/bash"]
        return [
            "/usr/bin/ssh", "-tt",
            "-p", PHONE_PORT,
            "-i", str(PHONE_KEY),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=20",
            f"{PHONE_USER}@{chosen}",
        ]
    # Default — interactive bash on kadx
    return ["/usr/bin/env", "-i", f"HOME={HOME}", f"USER={os.environ.get('USER','kadx')}",
            f"TERM=xterm-256color", "PATH=/home/kadx/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "/usr/bin/bash", "-l"]


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    rows = max(1, min(500, int(rows)))
    cols = max(1, min(500, int(cols)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def terminal_websocket(ws: WebSocket, cmd_kind: str = "local") -> None:
    await ws.accept()
    argv = _build_argv(cmd_kind)

    pid, master_fd = pty.fork()
    if pid == 0:
        # In child: exec the target program. pty.fork already attached stdio to slave.
        try:
            os.execvp(argv[0], argv)
        except FileNotFoundError:
            print(f"shadowops: argv[0] not found: {argv[0]}")
        os._exit(127)

    # Parent
    fcntl.fcntl(master_fd, fcntl.F_SETFL, os.O_NONBLOCK)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def on_readable() -> None:
        try:
            data = os.read(master_fd, 4096)
        except (OSError, BlockingIOError):
            return
        if not data:
            stop.set()
            return
        # Send raw bytes as binary frame so escape sequences survive untouched
        asyncio.create_task(_safe_send(ws, data))

    loop.add_reader(master_fd, on_readable)

    async def reader_from_client() -> None:
        try:
            while not stop.is_set():
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                # Control frames are JSON {"type":"resize","rows":N,"cols":N}
                text = msg.get("text")
                if text and text.startswith("{") and '"type"' in text:
                    try:
                        ctl = json.loads(text)
                        if ctl.get("type") == "resize":
                            _set_winsize(master_fd, ctl.get("rows", 24), ctl.get("cols", 80))
                            continue
                    except json.JSONDecodeError:
                        pass
                payload = (msg.get("bytes") if msg.get("bytes") is not None else (text or "").encode("utf-8"))
                if payload:
                    try:
                        os.write(master_fd, payload)
                    except OSError:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            stop.set()

    try:
        await asyncio.wait_for(asyncio.gather(reader_from_client(), stop.wait()), timeout=None)
    finally:
        loop.remove_reader(master_fd)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            await ws.close()
        except Exception:
            pass


async def _safe_send(ws: WebSocket, data: bytes) -> None:
    try:
        await ws.send_bytes(data)
    except Exception:
        pass
