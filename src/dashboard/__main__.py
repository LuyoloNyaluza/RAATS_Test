import os
import socket
import threading
import time
import webbrowser

import uvicorn


def _open_when_ready(host: str, port: int, url: str) -> None:
    """Open the browser once the server accepts connections (waits up to 15 s)."""
    for _ in range(60):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        return
    webbrowser.open(url)


if __name__ == "__main__":
    host, port = "127.0.0.1", int(os.environ.get("RAATS_DASH_PORT", "8000"))
    url = f"http://{host}:{port}"
    print(f"RAATS dashboard: {url}   (Ctrl+C to quit; the agent is a separate process)")
    if os.environ.get("RAATS_DASH_OPEN", "1") != "0":          # RAATS_DASH_OPEN=0: do not open a browser
        threading.Thread(target=_open_when_ready, args=(host, port, url), daemon=True).start()
    uvicorn.run("src.dashboard.app:app", host=host, port=port, log_level="warning")
