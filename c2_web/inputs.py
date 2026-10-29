"""Headless serial and HTTP snapshot adapters. No Tk imports or motor output."""
import asyncio
from collections import deque
from io import BytesIO
import time

import httpx
from PIL import Image
import serial
from serial.tools import list_ports


class GPSInput:
    def __init__(self):
        self.serial = None
        self.task = None
        self.source = "disconnected"
        self.error = None
        self.lines = deque(maxlen=512)

    async def connect(self, port, baud):
        await self.close()
        if port not in [p.device for p in list_ports.comports()]:
            raise ValueError("Select an available serial port")
        if baud not in (9600, 115200):
            raise ValueError("Use 9600 or 115200 baud")
        self.serial = await asyncio.to_thread(serial.Serial, port, baud, timeout=0.1)
        self.source, self.error = f"USB {port}", None
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            while self.serial and self.serial.is_open:
                data = await asyncio.to_thread(self.serial.readline, 161)
                if data:
                    self.lines.append((data.decode("ascii", errors="replace").strip(), time.monotonic()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = f"Serial input failed ({type(exc).__name__})"

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.serial:
            await asyncio.to_thread(self.serial.close)
        self.serial = self.task = None
        self.source, self.error = "disconnected", None
        self.lines.clear()


async def fetch_snapshot(url):
    if not url.startswith(("http://", "https://")):
        raise ValueError("Use an HTTP or HTTPS JPEG/PNG snapshot URL")
    chunks, size = [], 0
    async with httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0] not in ("image/jpeg", "image/png"):
                raise ValueError("Camera must return a JPEG or PNG image")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ValueError("Snapshot exceeds 4 MB")
                chunks.append(chunk)
    data = b"".join(chunks)
    with Image.open(BytesIO(data)) as im:
        if im.width * im.height > 16_000_000:
            raise ValueError("Snapshot dimensions exceed 16 megapixels")
        im.verify()
    return data
