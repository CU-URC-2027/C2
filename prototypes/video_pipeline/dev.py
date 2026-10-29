#!/usr/bin/env python3
import argparse
import json
import threading
import time
from urllib.request import urlopen
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Local video source node. No GitHub or physical camera access.")
    parser.add_argument("--port", type=int, default=8872)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port from 1024 to 65535")
    url = f"http://127.0.0.1:{args.port}"
    try:
        with urlopen(url+"/api/health", timeout=.5) as response:
            existing = json.load(response)
        if existing.get("service") == "urc-video-pipeline-prototype":
            print(f"Video lab already running: {url}")
            if args.open:
                webbrowser.open(url)
            return
        raise SystemExit(f"Port {args.port} belongs to a different service. Stop it or use --port; do not run two video labs on the default ports.")
    except (OSError, ValueError):
        pass
    if args.open:
        def open_ready():
            for _ in range(40):
                try:
                    with urlopen(url+"/api/health", timeout=.5):
                        webbrowser.open(url)
                        return
                except OSError:
                    time.sleep(.2)
        threading.Thread(target=open_ready, daemon=True).start()
    print(f"Local video lab: {url}\nSources start off. Enable video streams in the camera bank when needed.", flush=True)
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
