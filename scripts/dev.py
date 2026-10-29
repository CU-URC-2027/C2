#!/usr/bin/env python3
"""Start the local station. No auto connection or enable, no external listener."""
import argparse
import json
from pathlib import Path
import sys
import threading
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8870)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port from 1024 to 65535")
    url = f"http://127.0.0.1:{args.port}"
    try:
        with urlopen(url+"/api/health", timeout=.5) as response:
            existing = json.load(response)
        if existing.get("service") == "urc-c2-web":
            print(f"C2 is already running: {url}")
            if args.open:
                webbrowser.open(url)
            return
    except (OSError, ValueError):
        pass
    if args.open:
        def open_when_ready():
            import time
            for _ in range(30):
                try:
                    with urlopen(url+"/api/health", timeout=.5):
                        webbrowser.open(url)
                        return
                except OSError:
                    time.sleep(.2)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"URC command station: {url}\nCtrl+C to stop. Starts disconnected and disarmed.", flush=True)
    import uvicorn
    uvicorn.run("c2_web.api:app", host="127.0.0.1", port=args.port, log_level="info", ws_max_size=550000)


if __name__ == "__main__":
    main()
