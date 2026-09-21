#!/usr/bin/env python3
"""Keep TCS Adult Recess reachable through a stable GitHub Pages redirect.

This is intentionally small and dependency-free. It keeps the local signup app on
127.0.0.1:8765, keeps a Cloudflare quick tunnel pointed at it, and updates the
public GitHub Pages redirect whenever Cloudflare assigns a new quick-tunnel URL.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

APP_DIR = Path("/Users/Assistant/AI/projects/tcs-adult-recess")
LINK_REPO = Path("/Users/Assistant/AI/projects/tcs-adult-recess-link")
LOG_DIR = Path("/Users/Assistant/AI/logs/tcs-adult-recess")
RUN_DIR = Path("/Users/Assistant/AI/data/tcs-adult-recess/run")
CLOUDFLARED = Path("/Users/Assistant/AI/tools/bin/cloudflared")
PORT = "8765"
ACCESS_KEY = "8Hug_Dcb8Zy8HuIUIQvFOGOp"
ACCESS_PASSWORD = "TCSrecessAdult22"
APP_URL = f"http://127.0.0.1:{PORT}/?key={ACCESS_KEY}"
TUNNEL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


def run(cmd: list[str], cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=check)


def http_ok(url: str, timeout: int = 8) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "adult-recess-link-keeper/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def pid_alive(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def kill_pidfile(pid_file: Path) -> None:
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    except Exception:
        pass
    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)


def ensure_app() -> None:
    app_pid = RUN_DIR / "app.pid"
    if http_ok(APP_URL):
        return
    kill_pidfile(app_pid)
    # Clear any stale listener on 8765 before starting the app we manage.
    run(["/bin/sh", "-lc", f"lsof -tiTCP:{PORT} -sTCP:LISTEN | xargs -r kill"])
    env = os.environ.copy()
    env.update({"PORT": PORT, "ACCESS_KEY": ACCESS_KEY, "ACCESS_PASSWORD": ACCESS_PASSWORD})
    log = open(LOG_DIR / "app.log", "ab", buffering=0)
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(APP_DIR),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    app_pid.write_text(str(proc.pid))
    for _ in range(20):
        if http_ok(APP_URL):
            return
        time.sleep(0.5)
    raise RuntimeError("Adult Recess app did not become healthy on 127.0.0.1:8765")


def latest_tunnel_url() -> str | None:
    log_path = LOG_DIR / "cloudflared.log"
    if not log_path.exists():
        return None
    text = log_path.read_text(errors="ignore")[-20000:]
    matches = TUNNEL_RE.findall(text)
    return matches[-1] if matches else None


def start_tunnel() -> str:
    tunnel_pid = RUN_DIR / "cloudflared.pid"
    kill_pidfile(tunnel_pid)
    # Avoid dueling quick tunnels for the same origin.
    run(["/bin/sh", "-lc", f"pkill -f 'cloudflared tunnel --url http://127.0.0.1:{PORT}' || true"])
    log_path = LOG_DIR / "cloudflared.log"
    log = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    tunnel_pid.write_text(str(proc.pid))
    for _ in range(60):
        url = latest_tunnel_url()
        if url:
            return url
        if proc.poll() is not None:
            raise RuntimeError("cloudflared exited before producing a URL")
        time.sleep(1)
    raise RuntimeError("cloudflared did not produce a trycloudflare URL")


def ensure_tunnel() -> str:
    tunnel_pid = RUN_DIR / "cloudflared.pid"
    url = latest_tunnel_url()
    # A quick-tunnel process can stay alive while Cloudflare returns 530 for the
    # public URL, so verify the actual public route, not just the local PID.
    if pid_alive(tunnel_pid) and url and http_ok(f"{url}/?key={ACCESS_KEY}", timeout=12):
        return url
    return start_tunnel()


def render_index(target: str) -> str:
    href = f"{target}/?key={ACCESS_KEY}"
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url={href}">
  <title>TCS Adult Recess</title>
  <script>window.location.replace({href!r});</script>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 640px; margin: 12vh auto; padding: 24px; color: #22301d; background: #fbf8ef; }}
    a {{ color: #397420; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>TCS Adult Recess</h1>
  <p>Opening the signup page…</p>
  <p>If it does not open automatically, <a href="{href}">tap here</a>.</p>
</body>
</html>
'''


def update_pages_redirect(target: str) -> None:
    index = LINK_REPO / "index.html"
    new_content = render_index(target)
    if index.exists() and index.read_text() == new_content:
        return
    index.write_text(new_content)
    run(["git", "add", "index.html"], cwd=LINK_REPO, check=True)
    status = run(["git", "status", "--porcelain"], cwd=LINK_REPO, check=True).stdout.strip()
    if not status:
        return
    run(["git", "commit", "-m", f"Update live tunnel redirect to {target}"], cwd=LINK_REPO, check=True)
    run(["git", "push"], cwd=LINK_REPO, check=True)


def main() -> None:
    ensure_dirs()
    ensure_app()
    target = ensure_tunnel()
    update_pages_redirect(target)
    print(f"Stable URL: https://erck0004.github.io/tcs-adult-recess-link/ -> {target}/?key={ACCESS_KEY}")


if __name__ == "__main__":
    main()
