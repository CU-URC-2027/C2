"""Single owner of control state. Browser input expiry is independent of transport ticks."""
import asyncio
from collections import deque
import json
import math
import random
import tempfile
import time
from pathlib import Path

from .legacy import Control, JOINTS, RoverLink, MockRover, GPSData, nmea_sentence
from .legacy import integrate_pose, compare_log, metrics, ROOT
from .inputs import GPSInput, fetch_snapshot


def number(value, low=-1, high=1):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Expected a finite number between {low} and {high}")
    return float(value)


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [clean(v) for v in value]
    return value


class Runtime:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.control = Control()
        self.link = RoverLink()
        self.mock = None
        self.owner = None
        self.owner_seen = -math.inf
        self.clients = set()
        self.input_mode = "virtual"
        self.input = {"throttle": 0, "steering": 0, "deadman": False, "jog": 0}
        self.input_seq = -1
        self.last_input = -math.inf
        self.input_paused = False
        self.joint = "base"
        self.running = False
        self.task = None
        self.started = self.clock()
        self.last_tick = self.started
        self.sequence = 0
        self.pose = [0.0, 0.0, math.pi / 2]
        self.path = deque(maxlen=1000)
        self.history = deque(maxlen=200)
        self.records = deque(maxlen=12000)
        self.events = deque(maxlen=100)
        self.previous_reason = None
        self.gps = GPSData()
        self.gps_input = GPSInput()
        self.gps_mode = "disconnected"
        self.gps_records = deque(maxlen=20000)
        self.gps_error = None
        self.last_demo_gps = -math.inf
        self.rng = random.Random(42)
        self.comparison = {"label": "No comparison loaded", "pairs": [], "skipped": 0, "metrics": metrics([])}
        self.cameras = {k: {"id": k, "label": label, "mode": "off", "received": None,
                            "error": None, "frames": 0, "image": None, "task": None}
                        for k, label in (("front", "Front navigation"), ("gripper", "Gripper"),
                                         ("aux1", "Auxiliary 01"), ("aux2", "Auxiliary 02"))}
        self.event("Command station ready. Controls start disarmed.")

    def event(self, text, kind="info"):
        self.events.appendleft({"time_s": round(self.clock() - self.started, 2), "text": text, "kind": kind})

    def register(self, client):
        self.clients.add(client)
        if self.owner is None:
            self.claim(client)

    def claim(self, client):
        if self.owner not in (None, client):
            raise ValueError("Another browser owns the controls. Release control there first.")
        if self.owner != client:
            self.disarm("Browser control acquired; enable deliberately")
            self.input_seq = -1
            self.control.samples[self.control.source].received = -math.inf
        self.owner, self.owner_seen = client, self.clock()

    def unregister(self, client):
        self.clients.discard(client)
        if self.owner == client:
            self.disarm("Operator browser disconnected")
            self.owner = None

    def disarm(self, reason="Operator disarm"):
        self.control.disarm(reason)
        self.input["deadman"] = False
        self.input["jog"] = 0
        self.link.disable()

    def stop(self):
        self.control.stop()
        self.input["deadman"] = False
        self.input["jog"] = 0
        self.link.disable(latch=True)
        self.event("STOP latched. Reset leaves controls disabled.", "stop")

    def receive_input(self, data):
        seq = data.get("seq")
        if type(seq) is not int or seq <= self.input_seq:
            raise ValueError("Input sequence must increase")
        if type(data.get("deadman", False)) is not bool:
            raise ValueError("Deadman must be true or false")
        t, s, jog = (number(data.get(k, 0)) for k in ("throttle", "steering", "jog"))
        if self.input_paused:
            return
        if self.input_mode == "gamepad" and data.get("gamepad_connected") is not True:
            self.disarm("Gamepad unavailable")
            self.control.samples[self.control.source].received = -math.inf
            return
        now = self.clock()
        # Only a NEW browser input updates this timestamp. The 20 Hz service tick never does.
        self.control.receive(self.control.source, t, s, data.get("deadman", False), now)
        self.control.receive_jog(self.joint, jog, now)
        self.input = {"throttle": t, "steering": s, "deadman": data.get("deadman", False), "jog": jog}
        self.last_input, self.input_seq = now, seq

    async def action(self, client, name, data):
        if client not in self.clients:
            raise ValueError("Browser session is disconnected")
        if name == "claim":
            self.claim(client)
            return "Controls acquired"
        if name in ("stop", "disarm"):
            self.stop() if name == "stop" else self.disarm()
            return "STOP latched" if name == "stop" else "Controls disarmed"
        if client != self.owner:
            raise ValueError("This browser is view-only")
        self.owner_seen = self.clock()
        if name == "input":
            self.receive_input(data)
            return None
        if name == "heartbeat":
            return None
        if name == "release":
            self.disarm("Browser released controls")
            self.owner = None
        elif name == "enable":
            if self.input_mode == "rc-demo" and self.link.connected:
                raise ValueError("RC is a preview input; choose virtual stick or gamepad for chassis control")
            ok, reason = self.control.enable(self.clock())
            if not ok:
                raise ValueError(reason)
            if self.link.connected:
                try:
                    self.link.request_enable(self.clock())
                except (ValueError, OSError):
                    self.disarm("Rover did not accept enable")
                    raise
            self.event("Enable requested; hold drive to move")
        elif name == "reset_stop":
            if self.link.connected:
                self.link.reset_stop()
            self.control.reset_stop()
            self.event("STOP reset requested; controls remain disarmed")
        elif name == "input_mode":
            mode = data.get("mode")
            if mode not in ("virtual", "gamepad", "rc-demo"):
                raise ValueError("Unknown input mode")
            self.disarm("Input source changed")
            self.input_mode = mode
            self.control.select("RC" if mode == "rc-demo" else "Xbox")
            self.control.samples[self.control.source].received = -math.inf
            self.last_input = -math.inf
        elif name == "speed_limit":
            self.control.speed_limit = number(data.get("value"), 0.05, 0.25)
        elif name == "arm_mode":
            if self.link.connected:
                raise ValueError("Arm preview requires chassis disconnected; arm hardware transport is not implemented")
            if not self.control.armed:
                raise ValueError("Enable controls before selecting arm preview")
            self.control.arm_enabled = not self.control.arm_enabled
            self.control.jog = 0
        elif name == "joint":
            if data.get("joint") not in JOINTS:
                raise ValueError("Unknown joint")
            self.joint = data["joint"]
            self.control.jog = 0
        elif name == "connect":
            self.disconnect()
            if data.get("mode") == "mock":
                self.mock = MockRover()
                self.link.connect("127.0.0.1", self.mock.port)
                self.event("Local mock connected. No motor hardware.")
            elif data.get("mode") == "udp":
                port = data.get("port", 4210)
                if type(port) is not int:
                    raise ValueError("UDP port must be an integer")
                self.link.connect(str(data.get("host", "")), port)
                self.event("Chassis UDP connection requested")
            else:
                raise ValueError("Choose mock or UDP")
        elif name == "disconnect":
            self.disconnect()
        elif name == "mock_silent":
            if not self.mock:
                raise ValueError("Connect the local mock first")
            self.mock.silent = not self.mock.silent
        elif name == "input_pause":
            self.input_paused = not self.input_paused
            self.event("Browser input paused for timeout test" if self.input_paused else "Browser input resumed; re-enable deliberately")
        elif name == "reset_model":
            self.disarm("Model reset")
            self.pose = [0, 0, math.pi / 2]
            self.path.clear()
        elif name == "gps_mode":
            await self.gps_input.close()
            mode = data.get("mode")
            if mode not in ("disconnected", "demo", "rover", "serial"):
                raise ValueError("Unknown GPS source")
            self.gps = GPSData()
            self.gps_records.clear()
            self.gps_error = None
            self.gps_mode = mode
            if mode == "serial":
                try:
                    await self.gps_input.connect(str(data.get("port", "")), int(data.get("baud", 115200)))
                except Exception:
                    self.gps_mode = "disconnected"
                    raise
            self.event(f"GPS source: {mode}")
        elif name == "gps_reset":
            self.gps = GPSData()
            self.gps_records.clear()
        elif name == "gps_compare":
            content = data.get("content", "")
            if not isinstance(content, str) or len(content.encode()) > 512_000:
                raise ValueError("Comparison JSONL must be smaller than 512 KB")
            folder = ROOT / "data"
            folder.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=folder) as tmp:
                path = Path(tmp) / "comparison.jsonl"
                path.write_text(content)
                try:
                    pairs, skipped = compare_log(path)
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                    raise ValueError("Invalid comparison JSONL. Use origin, reference and GPS rows with finite coordinates and unique timestamps.") from exc
            self.comparison = {"label": "Imported reference comparison", "pairs": pairs[-1000:],
                               "skipped": skipped, "metrics": metrics(pairs)}
        elif name == "camera":
            await self.configure_camera(data)
        else:
            raise ValueError("Unknown action")
        return "Updated"

    def disconnect(self):
        self.disarm("Chassis disconnected")
        self.link.close()
        self.link = RoverLink()
        if self.mock:
            self.mock.close()
        self.mock = None

    async def configure_camera(self, data):
        key, mode = data.get("camera"), data.get("mode")
        if key not in self.cameras or mode not in ("off", "demo", "snapshot"):
            raise ValueError("Unknown camera or camera mode")
        camera = self.cameras[key]
        if camera["task"]:
            camera["task"].cancel()
            await asyncio.gather(camera["task"], return_exceptions=True)
        camera.update(mode=mode, received=None, error=None, frames=0, image=None, task=None)
        if mode == "snapshot":
            url = str(data.get("url", ""))
            if not url.startswith(("http://", "https://")):
                camera["mode"] = "off"
                raise ValueError("Use an HTTP/HTTPS JPEG or PNG snapshot URL")
            camera["task"] = asyncio.create_task(self.snapshot_loop(camera, url))

    async def snapshot_loop(self, camera, url):
        while True:
            try:
                camera["image"] = await fetch_snapshot(url)
                camera["received"] = self.clock()
                camera["frames"] += 1
                camera["error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                camera["error"] = f"Snapshot unavailable ({type(exc).__name__})"
            await asyncio.sleep(0.5)

    def consume_gps(self, line, now):
        parsed = self.gps.consume(line, now)
        self.gps_records.append({"type": "gps_capture", "source": self.gps_mode,
                                 "receipt_monotonic_s": now, "nmea": line, "parsed": parsed})

    def tick(self):
        now = self.clock()
        if self.owner and now - self.owner_seen > 5:
            self.disarm("Browser session expired")
            self.owner = None
        result = self.control.output(now)
        self.link.tick(result, now)
        if self.link.fault and self.link.connected:
            self.control.disarm(self.link.fault)
            result = self.control.output(now)
        dt = max(0, min(now - self.last_tick, 0.1))
        self.last_tick = now
        self.pose = list(integrate_pose(*self.pose, result["left"], result["right"], dt))
        self.path.append(self.pose[:2])
        rover_lines, self.link.gps_lines = self.link.gps_lines, []
        if self.gps_mode == "rover":
            if self.link.ready(now):
                for line in rover_lines:
                    self.consume_gps(line, now)
            else:
                self.gps.valid = False
        if self.gps_mode == "serial":
            self.gps_error = self.gps_input.error
            if self.gps_error:
                self.gps.valid = False
            while self.gps_input.lines:
                line, received = self.gps_input.lines.popleft()
                self.consume_gps(line, received)
        if self.gps_mode == "demo" and now - self.last_demo_gps >= 1:
            self.last_demo_gps = now
            east = self.pose[0] + 0.7 + self.rng.gauss(0, 0.3)
            north = self.pose[1] - 0.4 + self.rng.gauss(0, 0.3)
            def coord(deg):
                deg = abs(deg)
                return f"{int(deg):02d}{(deg % 1)*60:09.6f}"
            stamp = time.strftime("%H%M%S", time.gmtime())
            body = f"GPGGA,{stamp},{coord(north/111320)},{'N' if north >= 0 else 'S'},0{coord(east/111320)},{'E' if east >= 0 else 'W'},1,08,0.9,0.0,M,0.0,M,,"
            self.consume_gps(nmea_sentence(body), now)
        self.sequence += 1
        self.records.append(clean({"sequence": self.sequence, "time_s": now-self.started,
                                   "mode": self.mode, "operator_input_age_s": now-self.last_input,
                                   "control": result, "rover_state": self.link.state,
                                   "pose_model": dict(zip(("east_m", "north_m", "yaw_rad"), self.pose))}))
        if self.sequence % 2 == 0:
            self.history.append({"t": now-self.started, "left": result["left"], "right": result["right"],
                                 "rtt": self.link.rtt_ms})
        if result["reason"] != self.previous_reason:
            self.previous_reason = result["reason"]
            self.event(result["reason"], "fault" if "timeout" in result["reason"].lower() or self.link.fault else "info")

    @property
    def mode(self):
        return "mock" if self.mock else "udp" if self.link.connected else "model"

    def state(self):
        now = self.clock()
        result = self.control.output(now)
        fresh = self.gps.fresh(now) and self.gps_mode != "disconnected" and not self.gps_error
        return clean({
            "version": "0.1.0", "uptime_s": now-self.started, "sequence": self.sequence,
            "owner": self.owner, "clients": len(self.clients), "mode": self.mode,
            "input_mode": self.input_mode, "input": self.input, "input_age_s": now-self.last_input,
            "input_paused": self.input_paused, "speed_limit": self.control.speed_limit,
            "control": result, "arm_mode": self.control.arm_enabled, "joint": self.joint,
            "rover": {"connected": self.link.connected, "ready": self.link.ready(now),
                      "pending_enable": self.link.pending_arm is not None, "fault": self.link.fault,
                      "state": self.link.state, "rtt_ms": self.link.rtt_ms, "rejected": self.link.rejected,
                      "age_s": now-self.link.last_rx, "mock_silent": self.mock.silent if self.mock else False},
            "pose": self.pose, "path": list(self.path)[-400:], "history": list(self.history),
            "gps": {"mode": self.gps_mode, "fresh": fresh, "error": self.gps_error,
                    "latitude": self.gps.latitude if fresh else None, "longitude": self.gps.longitude if fresh else None,
                    "age_s": now-self.gps.last_fix, "satellites": self.gps.satellites,
                    "hdop": self.gps.hdop, "speed_mps": self.gps.speed_mps if now-self.gps.last_speed < 2.5 else None,
                    "bad": self.gps.bad, "duplicates": self.gps.duplicates, "samples": len(self.gps.samples),
                    "scatter": self.gps.scatter(), "track": [p[1:3] for p in list(self.gps.samples)[-400:]],
                    "origin": self.gps.origin, "records": len(self.gps_records), "comparison": self.comparison},
            "cameras": [{k: v for k, v in cam.items() if k not in ("image", "task", "received")} |
                        {"age_s": now-cam["received"] if cam["received"] is not None else None}
                        for cam in self.cameras.values()],
            "events": list(self.events), "log_rows": len(self.records),
            "capabilities": {"arm": "preview", "battery": "unavailable", "odometry": "model", "ros2": "planned"},
        })

    async def run(self):
        try:
            while self.running:
                started = self.clock()
                self.tick()
                await asyncio.sleep(max(0.001, 0.05 - (self.clock()-started)))
        except asyncio.CancelledError:
            raise

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self.run())

    async def close(self):
        self.running = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.disconnect()
        await self.gps_input.close()
        tasks = [c["task"] for c in self.cameras.values() if c["task"]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
