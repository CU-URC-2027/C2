"""Five persistent, uncompressed synthetic sources. No camera drivers or video codec.

Each FFmpeg process publishes fixed-size NV12 frames to a pipe. A reader drains it
at the source cadence and retains only the latest immutable frame. Browser preview
conversion happens separately, only while a visible node holds a short lease.
"""
import asyncio
from collections import deque
from dataclasses import dataclass
from io import BytesIO
import shutil
import subprocess
import threading
import time

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Specification:
    id: str
    name: str
    width: int
    height: int
    hue: int
    color: str
    fps: int = 30

    @property
    def frame_bytes(self):
        return self.width * self.height * 3 // 2

    def command(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is not on PATH. Install FFmpeg to run the synthetic sources.")
        pattern = f"testsrc2=size={self.width}x{self.height}:rate={self.fps}"
        filters = f"hue=h={self.hue}:s=0.9,drawbox=x=0:y=0:w=iw:h=ih:color=0x{self.color[1:]}:t=20,format=nv12"
        return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", "1",
                "-re", "-f", "lavfi", "-i", pattern, "-an", "-vf", filters,
                "-c:v", "rawvideo", "-pix_fmt", "nv12", "-threads:v", "1", "-f", "rawvideo", "pipe:1"]


SPECS = (
    Specification("cam-01", "Camera 01", 3840, 2160, 0, "#e9b86d"),
    Specification("cam-02", "Camera 02", 1920, 1080, 72, "#6edcc4"),
    Specification("cam-03", "Camera 03", 1920, 1080, 144, "#7cabef"),
    Specification("cam-04", "Camera 04", 1920, 1080, 216, "#bc99ec"),
    Specification("cam-05", "Camera 05", 1920, 1080, 288, "#ed91a7"),
)


def preview_jpeg(frame, spec, width=480):
    """Sample a small monitor image from the actual full-resolution NV12 buffer.

    Limited-range BT.601 approximation suffices for these synthetic test patterns.
    This monitor is not a color-validation path or a production video encoder.
    """
    height = width * spec.height // spec.width
    pixels = np.frombuffer(frame, dtype=np.uint8)
    plane = spec.width * spec.height
    y = pixels[:plane].reshape(spec.height, spec.width)
    uv = pixels[plane:].reshape(spec.height // 2, spec.width)
    ys = (np.arange(height) * spec.height // height)[:, None]
    xs = (np.arange(width) * spec.width // width)[None, :]
    luma = y[ys, xs].astype(np.int32) - 16
    u = uv[ys // 2, (xs // 2) * 2].astype(np.int32) - 128
    v = uv[ys // 2, (xs // 2) * 2 + 1].astype(np.int32) - 128
    rgb = np.stack(((298*luma+409*v+128) >> 8,
                    (298*luma-100*u-208*v+128) >> 8,
                    (298*luma+516*u+128) >> 8), axis=-1)
    out = BytesIO()
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(out, "JPEG", quality=75)
    return out.getvalue()


class Source:
    def __init__(self, spec):
        self.spec = spec
        self.process = self.thread = None
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0
        self.received = None
        self.timestamps = deque(maxlen=120)
        self.jpeg = None
        self.preview_sequence = 0
        self.preview_count = 0
        self.preview_received = None
        self.error = None
        self.started = None
        self.clients = 0
        self.consumer_skips = 0
        self.stop_event = threading.Event()

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.running:
            return
        self.stop()
        self.stop_event.clear()
        with self.lock:
            self.sequence = 0
            self.timestamps.clear()
            self.error = None
            self.started = time.monotonic()
        self.process = subprocess.Popen(self.spec.command(), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=self.spec.frame_bytes*2)
        self.thread = threading.Thread(target=self.read, args=(self.process,), daemon=True,
                                       name=self.spec.id)
        self.thread.start()

    def read(self, process):
        size = self.spec.frame_bytes
        period = 1 / self.spec.fps
        deadline = time.monotonic()
        try:
            while process.poll() is None:
                frame = process.stdout.read(size)
                if len(frame) != size:
                    break
                # Publish at real time without bursts after a scheduler stall.
                # The synthetic source's frame PTS is still exactly n / 30.
                if self.stop_event.wait(max(0, deadline-time.monotonic())):
                    break
                now = time.monotonic()
                with self.lock:
                    self.frame = frame
                    self.sequence += 1
                    self.received = now
                    self.timestamps.append(now)
                deadline += period
                if deadline < now:
                    deadline = now + period
            if process.poll() is None and not self.stop_event.is_set():
                process.wait(timeout=2)
            if not self.stop_event.is_set() and process.returncode not in (0, -9, -15):
                self.error = "Synthetic source failed. See the local terminal or restart sources."
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if process.poll() is None and not self.stop_event.is_set():
                self.error = "Source reader stopped unexpectedly."

    def stop(self):
        self.stop_event.set()
        process, thread = self.process, self.thread
        if process and process.poll() is None:
            # These processes write only disposable raw frames to a pipe.
            # Kill directly: graceful FFmpeg flushing can block on a full pipe
            # after its reader has been stopped. There is no file to finalize.
            process.kill()
            process.wait(timeout=2)
        if thread:
            thread.join(timeout=3)
        if process:
            process.stdout.close()
            process.stderr.close()
        self.process = self.thread = None
        with self.lock:
            self.frame = self.jpeg = None
            self.timestamps.clear()

    def latest(self):
        with self.lock:
            return self.sequence, self.frame, self.received

    def state(self):
        now = time.monotonic()
        with self.lock:
            stamps = list(self.timestamps)
            sequence, received = self.sequence, self.received
        fps = (len(stamps)-1)/(stamps[-1]-stamps[0]) if len(stamps)>1 else None
        return {"id": self.spec.id, "name": self.spec.name, "width": self.spec.width,
                "height": self.spec.height, "fps_target": self.spec.fps, "fps_actual": fps,
                "pixel_format": "nv12", "frame_bytes": self.spec.frame_bytes,
                "raw_mb_s": self.spec.frame_bytes*self.spec.fps/1_000_000,
                "color": self.spec.color, "hue": self.spec.hue, "sequence": sequence,
                "running": self.running, "process_pid": self.process.pid if self.running else None, "age_ms": (now-received)*1000 if received else None,
                "error": self.error, "preview_sequence": self.preview_sequence,
                "preview_count": self.preview_count, "preview_age_ms": (now-self.preview_received)*1000 if self.preview_received else None,
                "raw_consumers": self.clients, "consumer_skips": self.consumer_skips,
                "stream_path": f"/sources/{self.spec.id}.nv12"}


class Bank:
    def __init__(self):
        self.sources = {s.id: Source(s) for s in SPECS}
        self.leases = {}
        self.preview_task = None
        self.preview_busy = False
        self.running = False
        self.operation_lock = asyncio.Lock()

    @property
    def previews_enabled(self):
        now = time.monotonic()
        self.leases = {key: expiry for key, expiry in self.leases.items() if expiry > now}
        return bool(self.leases)

    async def start(self):
        self.running = True
        # Generation is opt-in. Preview visibility never starts a generator.
        self.preview_task = asyncio.create_task(self.previews())

    async def set_sources(self, enabled):
        async with self.operation_lock:
            await asyncio.gather(*(asyncio.to_thread(source.start if enabled else source.stop)
                                   for source in self.sources.values()))

    async def previews(self):
        while self.running:
            begin = time.monotonic()
            if self.previews_enabled:
                self.preview_busy = True
                try:
                    # Only small sampled RGB/JPEG images; full sources remain NV12.
                    await asyncio.gather(*(asyncio.to_thread(self.make_preview, source)
                                           for source in self.sources.values() if source.running))
                finally:
                    self.preview_busy = False
            await asyncio.sleep(max(.01, 1/6-(time.monotonic()-begin)))

    @staticmethod
    def make_preview(source):
        seq, frame, _ = source.latest()
        if frame is not None and seq != source.preview_sequence:
            source.jpeg = preview_jpeg(frame, source.spec)
            source.preview_sequence = seq
            source.preview_count += 1
            source.preview_received = time.monotonic()

    def state(self):
        return {"service": "urc-video-pipeline-prototype", "sources": [s.state() for s in self.sources.values()],
                "previews_enabled": self.previews_enabled, "preview_busy": self.preview_busy,
                "preview_width": 480, "preview_fps_target": 6,
                "encoder": None, "production_transport": None}

    async def close(self):
        self.running = False
        self.leases.clear()
        if self.preview_task:
            self.preview_task.cancel()
            await asyncio.gather(self.preview_task, return_exceptions=True)
        await self.set_sources(False)
