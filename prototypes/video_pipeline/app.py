"""Local-only companion UI. Temporary raw source URLs are a lab adapter."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from sources import Bank
from status_runtime import StatusRuntime
from simulated_link import LinkConfig
from decision_runtime import DecisionRuntime
from encoder_runtime import EncoderRuntime
from transmission import TransmissionRuntime

ROOT = Path(__file__).resolve().parent


def create_app(bank=None, status_runtime=None, encoder_runtime=None):
    bank = bank or Bank()
    status = status_runtime or StatusRuntime(bank.sources.keys())
    decision = DecisionRuntime(bank, status)
    encoder = encoder_runtime or EncoderRuntime(bank, decision)
    transmission = TransmissionRuntime(encoder, decision, status)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await bank.start()
            await status.start()
            await decision.start()
            await encoder.start()
            await transmission.start()
            yield
        finally:
            await transmission.close()
            await encoder.close()
            await decision.close()
            await status.close()
            await bank.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.bank = bank
    app.state.status_runtime = status
    app.state.decision_runtime = decision
    app.state.encoder_runtime = encoder
    app.state.transmission_runtime = transmission

    def actual_encoder_state():
        return dict(encoder.state(), transmission_connected=any(j.connected for j in transmission.jobs.values()))

    def architecture_state():
        return dict(status.state(), encoding_decision=dict(decision.state(), encoder_connected=encoder.enabled),
                    encoder=actual_encoder_state(), transmission=transmission.state())

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.hostname not in ("127.0.0.1", "localhost", "testserver") or (
            origin is not None and origin != f"http://{request.headers.get('host')}"):
            return Response("Local same-origin access only", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/api/state")
    async def state():
        return dict(bank.state(), encoder={"enabled": encoder.enabled, "state_url": "/api/encoder"},
                    architecture=architecture_state())

    @app.get("/api/encoding-decision")
    async def decision_output():
        return dict(decision.state(), encoder_connected=encoder.enabled)

    @app.get("/api/transmission")
    async def transmission_output():
        return transmission.state()

    @app.post("/api/transmission/config")
    async def transmission_config(request: Request):
        try:
            await transmission.configure(await request.json())
            return transmission.state()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/transmission/reconnect")
    async def transmission_reconnect():
        await transmission.reconnect()
        return transmission.state()

    @app.get("/api/encoder")
    async def encoder_output():
        return actual_encoder_state()

    @app.post("/api/encoder/enabled")
    async def encoder_enable(request: Request):
        try:
            row = await request.json()
            if not isinstance(row, dict) or set(row) != {"enabled"}:
                raise ValueError("Supply only enabled")
            await encoder.set_enabled(row["enabled"])
            return actual_encoder_state()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/encoder/previews/{client}")
    async def encoder_preview_lease(client: str, request: Request):
        try:
            row = await request.json()
            encoder.preview(client, row.get("visible") if isinstance(row, dict) else None)
            return {"enabled": encoder.previews_enabled}
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/encoder/preview/{key}.jpg")
    async def encoded_preview(key: str):
        if key not in bank.sources:
            raise HTTPException(404, "Unknown camera")
        frame = encoder.jpeg(key)
        if frame is None:
            raise HTTPException(404, "Encoded preview is hidden, inactive or waiting for a keyframe")
        return Response(frame[0], media_type="image/jpeg", headers={"X-Encoded-PTS-Ns": str(frame[1])})

    @app.get("/api/encoder/capture/{key}")
    async def encoded_capture(key: str):
        if key not in bank.sources:
            raise HTTPException(404, "Unknown camera")
        frames = encoder.hub.capture(key)
        if not frames:
            raise HTTPException(409, "No complete current-epoch GOP is available")
        return Response(b"".join(f.data for f in frames), media_type="video/h264", headers={
            "Content-Disposition": f'attachment; filename="{key}-{frames[0].encoder_session[:8]}.h264"',
            "X-Encoder-Session": frames[0].encoder_session, "X-Encoded-Frames": str(len(frames))})

    @app.post("/api/encoding-decision/config")
    async def decision_config(request: Request):
        try:
            row = await request.json()
            if not isinstance(row, dict) or set(row) != {"video_share_percent"}:
                raise ValueError("Supply only video_share_percent")
            decision.configure(row["video_share_percent"])
            transmission.refresh_plan(force=True)
            return decision.state()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/status-manager")
    async def manager_output():
        return status.manager.snapshot()

    @app.post("/api/link")
    async def link(request: Request):
        try:
            row = await request.json()
            if not isinstance(row, dict):
                raise ValueError("Expected link inputs")
            status.configure_link(LinkConfig(row.get("bandwidth_bps"), row.get("latency_ms", 40)))
            decision.evaluate()
            return architecture_state()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/health")
    async def health():
        return {"service": "urc-video-pipeline-prototype", "sources": sum(s.running for s in bank.sources.values())}

    @app.post("/api/previews/{client}")
    async def previews(client: str, request: Request):
        if len(client) > 64:
            raise HTTPException(400, "Invalid preview session")
        data = await request.json()
        if data.get("visible") is True:
            import time
            bank.leases[client] = time.monotonic()+5
        else:
            bank.leases.pop(client, None)
        return {"enabled": bank.previews_enabled}

    @app.post("/api/sources")
    async def sources(request: Request):
        data = await request.json()
        if type(data.get("running")) is not bool:
            raise HTTPException(400, "running must be true or false")
        if not data["running"]:
            await encoder.sources_stopping()
        await bank.set_sources(data["running"])
        decision.evaluate()
        if data["running"]:
            await encoder.sources_started()
        return bank.state()

    @app.get("/preview/{key}.jpg")
    async def preview(key: str):
        source = bank.sources.get(key)
        if not source:
            raise HTTPException(404, "Unknown source")
        if not source.jpeg or not source.running or not bank.previews_enabled:
            raise HTTPException(404, "Preview is hidden, paused or starting")
        return Response(source.jpeg, media_type="image/jpeg", headers={
            "X-Source-Sequence": str(source.preview_sequence), "X-Preview-Width": "480"})

    @app.get("/sources/{key}.nv12")
    async def raw(key: str, request: Request, frames: int = 0):
        """Uncompressed local test feed. No headers inside the fixed-size frames.

        Slow consumers skip to the newest frame rather than growing a queue.
        HTTP rawvideo does not carry capture timestamps; later architecture work
        must choose timestamp-preserving handoff before latency measurements.
        """
        source = bank.sources.get(key)
        if not source:
            raise HTTPException(404, "Unknown source")
        if not source.running:
            raise HTTPException(409, "Sources are paused")
        if not 0 <= frames <= 300:
            raise HTTPException(400, "Use 0 for persistent output or 1–300 for a finite probe")
        if source.clients >= 2:
            raise HTTPException(429, "Two raw consumers already attached to this source")
        source.clients += 1

        async def stream():
            last, count = -1, 0
            try:
                while source.running and not await request.is_disconnected():
                    seq, frame, _ = source.latest()
                    if frame is not None and seq != last:
                        if last >= 0 and seq > last:
                            source.consumer_skips += max(0, seq-last-1)
                        last, count = seq, count+1
                        yield frame
                        if frames and count >= frames:
                            break
                    await asyncio.sleep(.002)
            finally:
                source.clients -= 1

        return StreamingResponse(stream(), media_type="application/octet-stream", headers={
            "X-Pixel-Format": "nv12", "X-Width": str(source.spec.width),
            "X-Height": str(source.spec.height), "X-Framerate": "30",
            "X-Frame-Bytes": str(source.spec.frame_bytes)})

    app.mount("/assets", StaticFiles(directory=ROOT/"web"), name="assets")

    @app.get("/")
    async def home():
        return FileResponse(ROOT/"web/index.html")

    return app


app = create_app()
