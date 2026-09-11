"""Run a real Waitress process with Render-like environment settings, then stop it.

This checks the local build, not a deployed Render service or the Chromebook.
It performs one real outbound request to https://example.com.
"""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests


def main():
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    key = secrets.token_urlsafe(32)
    origin = "https://relay-smoke-test.onrender.com"
    environment = dict(os.environ, RENDER="true", HOSTED_MODE="true", GOOGLE_SITES_EMBED="false", PORT=str(port),
                       RENDER_EXTERNAL_URL=origin, PUBLIC_BASE_URL=origin,
                       GATEWAY_AUTH_KEY=key, DEBUG="false", ALLOW_UNAUTHENTICATED_REMOTE="false")
    process = subprocess.Popen([sys.executable, "app.py"], cwd=str(root), env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = "http://127.0.0.1:{}".format(port)
    try:
        with requests.Session() as session:
            session.trust_env = False
            for attempt in range(50):
                if process.poll() is not None:
                    raise RuntimeError("Render-mode server exited during startup.")
                try:
                    health = session.get(base + "/healthz", timeout=1)
                    if health.status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Server did not become healthy.")
            assert health.json() == {"status": "ok"}
            assert session.get(base + "/", timeout=5).status_code == 401
            session.headers["X-Gateway-Key"] = key
            home = session.get(base + "/", timeout=5)
            assert home.status_code == 200 and "Hosted on Render" in home.text
            assert session.get(base + "/status", timeout=5).json()["status"] == "online"
            page = session.get(base + "/proxy", params={"url": "https://example.com"}, timeout=40)
            assert page.status_code == 200, "Upstream example.com check returned HTTP {}".format(page.status_code)
            assert "Example Domain" in page.text
            assert 'href="' + origin + '/"' in page.text
            assert "http://" not in page.headers["Content-Security-Policy"]
            print("PASS: Render-mode startup, port binding, public health, protected UI/status, real HTTPS fetch, and HTTPS rewriting.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
