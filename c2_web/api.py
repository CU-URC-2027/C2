"""Loopback-only operator station. HTTP for resources, WebSocket for control/state."""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
import math
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from serial.tools import list_ports

from .legacy import ROOT
from .runtime import Runtime, clean
from .video_receiver import VideoReceiver
from .video_wire import pack_browser


def same_origin(headers):
    origin = headers.get("origin")
    return origin is None or origin in (f"http://{headers.get('host')}", f"https://{headers.get('host')}")


def create_app(runtime=None, video_receiver=None):
    station = runtime or Runtime()
    video = video_receiver or VideoReceiver()

    @asynccontextmanager
    async def lifespan(app):
        await station.start()
        try:
            await video.start()
            yield
        finally:
            await video.stop()
            await station.close()

    app = FastAPI(title="URC C2", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.station = station
    app.state.video_receiver = video

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if not same_origin(request.headers):
            return Response("Cross-origin requests are not allowed", status_code=403)
        # Host validation also prevents DNS rebinding into the local control API.
        if request.url.hostname not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return Response("Use the local loopback address", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'"
        return response

    @app.get("/api/health")
    async def health():
        return {"service": "urc-c2-web", "version": "0.2.0-NET5", "pid": os.getpid(),
                "tick": station.sequence, "running": station.running}

    @app.get("/api/state")
    async def state():
        return station.state()

    @app.get("/api/video/priorities")
    async def video_priorities():
        return station.video.state()

    @app.get("/api/ports")
    async def ports():
        return [{"device": p.device, "description": p.description} for p in list_ports.comports()]

    def jsonl(rows, filename):
        body = "".join(json.dumps(clean(row), allow_nan=False)+"\n" for row in rows)
        return Response(body, media_type="application/x-ndjson", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/logs/commands")
    async def commands():
        return jsonl(list(station.records), "c2-command-log.jsonl")

    @app.get("/api/logs/onboard")
    async def onboard_log():
        return jsonl(list(station.onboard.records) if station.onboard else [], "c2-onboard-chassis.jsonl")

    @app.get("/api/logs/first-fault")
    async def first_fault():
        return jsonl([station.last_fault_snapshot] if station.last_fault_snapshot else [], "c2-first-fault.jsonl")

    @app.get("/api/logs/gps")
    async def gps_log():
        return jsonl(list(station.gps_records), "c2-gps-capture.jsonl")

    @app.get("/api/gps/example")
    async def example():
        rows = [{"type": "origin", "latitude": 0, "longitude": 0}]
        for i in range(10):
            rows += [{"type": "reference", "time_s": i, "east_m": i*.2, "north_m": 0},
                     {"type": "gps", "time_s": i, "valid": True, "latitude": .000003,
                      "longitude": (i*.2+.7)/111320}]
        return jsonl(rows, "synthetic-comparison.jsonl")

    @app.get("/api/cameras/{camera}/image")
    async def camera_image(camera: str):
        cam = station.cameras.get(camera)
        if not cam:
            raise HTTPException(404, "Unknown camera")
        if cam["mode"] == "demo":
            now = station.clock()-station.started
            image = Image.new("RGB", (640, 360), "#101e2c")
            draw = ImageDraw.Draw(image)
            for x in range(0, 640, 40):
                draw.line((x, 0, x, 360), fill="#20364a")
            for y in range(0, 360, 40):
                draw.line((0, y, 640, y), fill="#20364a")
            x = 320+int(140*math.sin(now*.7))
            draw.rectangle((x-30, 160, x+30, 210), outline="#55d9bd", width=3)
            draw.text((22, 20), f"{cam['label'].upper()} / SYNTHETIC SNAPSHOT", fill="#55d9bd", font_size=18)
            draw.text((22, 325), f"C2 BENCH   T+{now:08.1f}s   NO CAMERA CONNECTED", fill="#c0cedb", font_size=16)
            stream = BytesIO()
            image.save(stream, format="JPEG", quality=80)
            cam["frames"] += 1
            cam["received"] = station.clock()
            return Response(stream.getvalue(), media_type="image/jpeg")
        if cam["image"]:
            return Response(cam["image"], media_type="image/png" if cam["image"].startswith(b"\x89PNG") else "image/jpeg")
        raise HTTPException(404, "No camera frame available")

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if not same_origin(ws.headers) or ws.url.hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
            await ws.close(code=1008)
            return
        await ws.accept()
        client = uuid.uuid4().hex
        station.register(client)
        send_lock = asyncio.Lock()

        async def send(payload):
            async with send_lock:
                await asyncio.wait_for(ws.send_json(payload), 1)

        async def broadcast():
            try:
                while True:
                    await send({"type": "state", "state": station.state()})
                    await asyncio.sleep(.1)
            except (RuntimeError, asyncio.TimeoutError, WebSocketDisconnect):
                # A browser that cannot receive state loses its operator session.
                station.unregister(client)
                await ws.close(code=1011)

        await send({"type": "hello", "client": client})
        broadcaster = asyncio.create_task(broadcast())
        try:
            while True:
                raw = await ws.receive_text()
                request_id, action = None, None
                try:
                    if len(raw.encode()) > 540000:
                        raise ValueError("Message exceeds size limit")
                    message = json.loads(raw)
                    if not isinstance(message, dict) or not isinstance(message.get("data", {}), dict):
                        raise ValueError("Expected an action object")
                    request_id, action = message.get("request_id"), message.get("action")
                    result = await station.action(client, action, message.get("data", {}))
                    if request_id is not None:
                        await send({"type": "ack", "request_id": request_id, "ok": True, "message": result or "Accepted"})
                except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
                    if station.owner == client and action in ("input", "enable", None):
                        station.disarm("Invalid browser command; enable again")
                    await send({"type": "ack", "request_id": request_id, "ok": False,
                                "message": str(exc) if isinstance(exc, ValueError) else f"Request failed ({type(exc).__name__})"})
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            station.unregister(client)
            broadcaster.cancel()
            await asyncio.gather(broadcaster, return_exceptions=True)

    @app.get("/api/live-video/state")
    async def live_video_state():
        return video.state()

    @app.post("/api/live-video/restart")
    async def live_video_restart():
        await video.restart()
        return video.state()

    @app.websocket("/ws/video/{stream_id}")
    async def live_video_socket(ws: WebSocket, stream_id: str):
        if not same_origin(ws.headers) or ws.url.hostname not in ("localhost", "127.0.0.1", "::1", "testserver") or stream_id not in video.channels:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            viewer = video.subscribe(stream_id)
        except ValueError:
            await ws.close(code=1013)
            return

        async def receive_reports():
            while True:
                raw = await ws.receive_text()
                if len(raw) > 2048:
                    raise ValueError("Video telemetry too large")
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError("Expected video telemetry object")
                if row.get("type") == "keyframe":
                    viewer.clear()
                    viewer.channel.request_keyframe = True
                else:
                    viewer.update_report(row)

        reports = asyncio.create_task(receive_reports())
        last_status = 0
        try:
            while True:
                if reports.done():
                    reports.result()
                    break
                frame = viewer.pop()
                if frame:
                    await asyncio.wait_for(ws.send_bytes(pack_browser(*frame)), .4)
                if time.monotonic()-last_status > .5:
                    await asyncio.wait_for(ws.send_json({"type": "status", "camera": viewer.channel.state(), "receiver_pid": os.getpid()}), .4)
                    last_status = time.monotonic()
                await asyncio.sleep(.002 if frame else .01)
        except (WebSocketDisconnect, RuntimeError, TimeoutError, ValueError, TypeError):
            pass
        finally:
            reports.cancel()
            await asyncio.gather(reports, return_exceptions=True)
            video.unsubscribe(viewer)
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

    @app.get("/")
    async def home():
        return FileResponse(ROOT / "web" / "index.html")

    return app


app = create_app(video_receiver=VideoReceiver(port=int(os.environ.get("C2_VIDEO_TCP_PORT", "8874"))))
