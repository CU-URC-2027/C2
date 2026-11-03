"""Single owner of control state. Browser input expiry is independent of transport ticks."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import math
import random
import tempfile
import time
from pathlib import Path

from .legacy import Control, JOINTS, RoverLink, MockRover, GPSData, nmea_sentence
from .legacy import integrate_pose, compare_log, metrics, ROOT
from .inputs import GPSInput, fetch_snapshot
from .priorities import VideoPriorities
from .onboard import OnboardOperator, ros_available, CLAIM, ENABLE, RESET
from .file_logging import DiagnosticLog
from .rover_discovery import RoverDiscovery, RoverProfiles
from urc_c2_chassis.policy import EncoderRates


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
        self.onboard = None
        self.video = VideoPriorities(clock)
        self.encoder_rates = EncoderRates()
        self.last_encoder_state = -1
        self.last_fault_snapshot = None
        self.fault_history = deque(maxlen=8)
        self.owner = None
        self.owner_seen = -math.inf
        self.clients = set()
        self.input_mode = "virtual"
        self.input = {"throttle": 0, "steering": 0, "deadman": False, "jog": 0}
        self.input_seq = -1
        self.last_input = -math.inf
        self.input_paused = False
        self.input_available = True
        self.last_valid_input_seq = -1
        self.browser_input = {}
        self.discovery, self.profiles = RoverDiscovery(), RoverProfiles()
        self.profile_task = None
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
        self.file_log = DiagnosticLog(ROOT)
        self.log_task = None
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
        row = {"time_s": round(self.clock() - self.started, 2), "text": text, "kind": kind}
        self.events.appendleft(row)
        self.file_log.submit("event", row)

    def register(self, client):
        self.clients.add(client)
        self.file_log.submit("browser_session", {"event": "connected", "client": client})
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
        self.file_log.submit("browser_session", {"event": "disconnected", "client": client})
        if self.owner == client:
            self.disarm("Operator browser disconnected")
            self.owner = None

    def disarm(self, reason="Operator disarm"):
        self.control.disarm(reason)
        self.input["deadman"] = False
        self.input["jog"] = 0
        self.link.disable()
        if self.onboard:
            self.onboard.disarm()

    def stop(self):
        self.control.stop()
        self.input["deadman"] = False
        self.input["jog"] = 0
        self.link.disable(latch=True)
        if self.onboard:
            self.onboard.disarm(latch=True)
        self.event("STOP latched. Reset leaves controls disabled.", "stop")

    def receive_input(self, data):
        seq = data.get("seq")
        if type(seq) is not int or seq <= self.input_seq:
            raise ValueError("Input sequence must increase")
        if type(data.get("deadman", False)) is not bool:
            raise ValueError("Deadman must be true or false")
        t, s, jog = (number(data.get(k, 0)) for k in ("throttle", "steering", "jog"))
        context = data.get("context", {})
        if isinstance(context, dict):
            context = {k: v[:160] if isinstance(v, str) else v for k, v in context.items()
                       if k in ("controller_id", "mapping", "stick", "error", "focused", "visible",
                                "throttle_axis", "steering_axis", "hold_button") and type(v) in (str, bool, int)}
            if context != self.browser_input:
                self.file_log.submit("browser_input_context", context)
                self.browser_input = context
        if self.input_paused:
            return
        if self.input_mode == "gamepad" and data.get("gamepad_connected") is not True:
            if self.input_available or self.control.armed:
                self.disarm("Gamepad unavailable")
                self.event("Gamepad unavailable; controls disarmed. Check mapping and press a controller button.")
            self.input_available = False
            self.input_seq = seq  # Consume ordering, never renew the valid-input clock.
            self.input = dict(throttle=0, steering=0, deadman=False, jog=0)
            self.last_input = -math.inf
            self.control.samples[self.control.source].received = -math.inf
            return
        if not self.input_available:
            self.event("Input recovered; neutralize and enable deliberately")
        self.input_available = True
        now = self.clock()
        # Only a NEW browser input updates this timestamp. The 20 Hz service tick never does.
        self.control.receive(self.control.source, t, s, data.get("deadman", False), now)
        self.control.receive_jog(self.joint, jog, now)
        self.input = {"throttle": t, "steering": s, "deadman": data.get("deadman", False), "jog": jog}
        self.last_input, self.input_seq = now, seq
        self.last_valid_input_seq = seq
        if self.onboard:
            self.onboard.input(t, s, data.get("deadman", False), self.control.speed_limit)

    async def action(self, client, name, data):
        # Allowlist diagnostic parameters: never log imported JSONL, snapshot URLs
        # (which can contain credentials), arbitrary content or video payloads.
        action_name = name[:80] if isinstance(name, str) else "invalid_action"
        keys = {"connect": ("mode", "host", "port", "namespace"), "input_mode": ("mode",),
                "input": ("seq", "throttle", "steering", "deadman", "jog", "gamepad_connected"),
                "disarm": ("reason",),
                "joint": ("joint",), "speed_limit": ("value",),
                "mock_options": ("reply_delay_ms", "drop_commands")}.get(action_name, ())
        details = clean({key: data[key][:256] if isinstance(data[key], str) else
                         data[key] if type(data[key]) in (bool, int, float, type(None)) else "invalid_value"
                         for key in keys if key in data})
        context = {"client": client, "action": action_name, "parameters": details}
        if name not in ("input", "heartbeat"):
            self.file_log.submit("action_request", context)
        try:
            result = await self._action(client, name, data)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.file_log.submit("action_rejected", context | {"error": str(exc),
                                 "error_type": type(exc).__name__, "diagnostics": self.log_context()})
            raise
        if name not in ("input", "heartbeat"):
            self.file_log.submit("action_result", context | {"result": result, "diagnostics": self.log_context()})
        return result

    def log_context(self):
        return clean({"mode": self.mode, "owner": self.owner, "input_mode": self.input_mode,
                      "input_seq": self.input_seq, "input_age_s": self.clock()-self.last_input,
                      "input_paused": self.input_paused, "control": self.control.output(self.clock()),
                      "browser_input": self.browser_input, "last_valid_input_seq": self.last_valid_input_seq,
                      "rover_diagnostics": self.link.diagnostics(self.clock()),
                      "rover_fault": self.link.fault, "first_fault": self.last_fault_snapshot,
                      "onboard": self.onboard.state() if self.onboard else None})

    async def _action(self, client, name, data):
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
        if name == "file_logging":
            if type(data.get("enabled")) is not bool:
                raise ValueError("Logging enabled must be true or false")
            if self.log_task and not self.log_task.done():
                raise ValueError("File logging is still starting or stopping")
            initial = self.log_context()
            async def configure():
                try:
                    if data["enabled"]:
                        await asyncio.to_thread(self.file_log.start, data.get("directory"), initial)
                    else:
                        await asyncio.to_thread(self.file_log.stop)
                    self.event("File logging enabled" if self.file_log.enabled else "File logging off")
                except ValueError as exc:
                    self.event(str(exc), "error")
            # Return immediately so this WebSocket can keep receiving fresh INPUT
            # while a folder/network disk is being opened or flushed.
            self.log_task = asyncio.create_task(configure())
            return "Starting file logging" if data["enabled"] else "Stopping file logging"
        if name == "release":
            self.disarm("Browser released controls")
            self.owner = None
        elif name == "enable":
            if self.link.fault:
                raise ValueError(self.link.fault)
            if self.input_mode == "rc-demo" and (self.link.connected or self.onboard):
                raise ValueError("RC is a preview input; choose virtual stick or gamepad for chassis control")
            if self.link.connected and not self.direct_enable_ready():
                raise ValueError("Wait for a fresh post-handshake acknowledgment before enabling")
            ok, reason = self.control.enable(self.clock())
            if not ok:
                raise ValueError(reason)
            if self.onboard:
                try:
                    self.onboard.command(ENABLE, (self.input["throttle"], self.input["steering"], self.input["deadman"]))
                except (ValueError, OSError):
                    self.disarm("Onboard Enable refused; inspect feedback")
                    raise
            if self.link.connected:
                try:
                    self.link.request_enable(self.clock())
                except (ValueError, OSError):
                    self.disarm("Rover did not accept enable")
                    raise
            self.event("Enable requested; hold drive to move")
        elif name == "reset_stop":
            if self.onboard:
                self.onboard.command(RESET)
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
            self.input_available = mode != "gamepad"
            self.control.select("RC" if mode == "rc-demo" else "Xbox")
            self.control.samples[self.control.source].received = -math.inf
            self.last_input = -math.inf
        elif name == "speed_limit":
            limit = number(data.get("value"), 0, self.pwm_limit_max())
            if limit>self.control.speed_limit and self.control.armed:
                self.disarm("PWM cap increased; enable deliberately at neutral")
            self.control.speed_limit = limit
        elif name == "arm_mode":
            if self.onboard or self.link.connected:
                raise ValueError("Disconnect the chassis transport before using the bench arm preview.")
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
            self.begin_link_session()
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
            elif data.get("mode") in ("oc-mock", "ros2"):
                self.onboard = OnboardOperator(data["mode"], data.get("namespace", ""))
                self.event("Onboard operator connected; Claim onboard control before Enable")
            else:
                raise ValueError("Choose local mock, UDP, OC loopback or ROS 2")
        elif name == "find_rovers":
            if self.control.armed or self.link.pending_arm or self.link.disarm_pending or (self.link.state or {}).get("enabled"):
                raise ValueError("Disarm and confirm disabled outputs before discovery")
            self.discovery.start(data.get("host", "255.255.255.255"), data.get("port",4210), data.get("local_ipv4","0.0.0.0"))
            self.event("Read-only rover discovery started; no control ownership or motion requested")
        elif name in ("connect_discovered", "connect_saved"):
            if self.control.armed or self.link.pending_arm or self.link.disarm_pending or (self.link.state or {}).get("enabled"):
                raise ValueError("Disarm before connecting another rover")
            if name == "connect_saved":
                row = next((r for r in self.profiles.profiles if r["id"]==data.get("id")),None)
                if not row: raise ValueError("Choose a saved rover")
                host, port, identity = row["host"], row["port"], row["device_id"]
            else:
                if self.discovery.state()["scanning"]: raise ValueError("Wait for discovery to finish")
                row = next((r for r in self.discovery.candidates if f"{r['device_id']}@{r['host']}:{r['control_port']}"==data.get("id")),None)
                if not row: raise ValueError("Choose a discovered rover")
                if row["busy"]: raise ValueError("This rover reports another active owner or enabled outputs; no takeover attempted")
                host, port, identity = row["host"], row["control_port"], row["device_id"]
            self.begin_link_session()
            self.link.connect(host,port,expected_device_id=identity)
            self.event("Rover handshake requested; identity will be verified before Enable")
        elif name == "save_rover":
            if not self.link.ready(self.clock()) or not self.link.state:
                raise ValueError("Connect and verify the rover before saving its profile")
            if self.profile_task and not self.profile_task.done(): raise ValueError("Profile save still in progress")
            row = self.profiles.validate({"name":data.get("name"), "host":self.link.target[0],
                     "port":self.link.target[1], "device_id":self.link.state.get("device_id")})
            async def save_profile():
                try:
                    await asyncio.to_thread(self.profiles.save,row)
                    self.event("Rover profile saved; reconnect remains disarmed")
                except (ValueError,OSError) as exc:
                    self.event(str(exc),"error")
            self.profile_task = asyncio.create_task(save_profile())
        elif name == "onboard_claim":
            if not self.onboard:
                raise ValueError("Connect an onboard transport first")
            self.disarm("Claiming onboard control")
            self.onboard.command(CLAIM)
        elif name == "video_priorities":
            self.video.update(data.get("ordered_stream_ids"), data.get("enabled_count"), data.get("expected_revision"))
            self.event(f"Video priorities updated to revision {self.video.revision}")
        elif name == "video_destination":
            self.video.destination(data.get("host"), data.get("port"), data.get("enabled"))
        elif name == "disconnect":
            self.disconnect()
        elif name == "mock_silent":
            if not self.mock:
                raise ValueError("Connect the local mock first")
            self.mock.silent = not self.mock.silent
        elif name == "mock_options":
            if not self.mock:
                raise ValueError("Connect the direct NET5 local mock first")
            delay = number(data.get("reply_delay_ms", 0), 0, 150)
            if type(data.get("drop_commands", False)) is not bool:
                raise ValueError("Drop commands must be a Boolean")
            self.mock.reply_delay = delay/1000
            self.mock.drop_commands = data.get("drop_commands", False)
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
        self.control.speed_limit = min(self.control.speed_limit,.25)
        if self.link.fault_snapshot:
            self.last_fault_snapshot = self.link.fault_snapshot
        if self.onboard:
            self.onboard.close()
            self.onboard = None
        self.link.close()
        self.link = RoverLink()
        if self.mock:
            self.mock.close()
        self.mock = None
        self.encoder_rates.invalidate()
        self.last_encoder_state = -1

    def begin_link_session(self):
        self.disconnect()
        if self.last_fault_snapshot:
            archived = {"archived_utc":datetime.now(timezone.utc).isoformat(),"snapshot":self.last_fault_snapshot}
            self.fault_history.append(archived)
            self.file_log.submit("fault_archived",archived)
        self.last_fault_snapshot = None

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
        self.control.speed_limit = min(self.control.speed_limit,self.pwm_limit_max())
        if self.owner and now - self.owner_seen > 5:
            self.disarm("Browser session expired")
            self.owner = None
        result = self.control.output(now)
        self.link.tick(result, now)
        self.video.tick()
        if self.onboard:
            self.onboard.source_label = self.input_mode
            self.onboard.tick()
            if self.onboard.fault:
                self.control.stop("Onboard feedback interrupted; Reset STOP required")
            elif not self.control.armed and self.onboard.permit:
                self.onboard.disarm()
            result = self.control.output(now)
        if self.link.fault and self.link.connected:
            self.control.disarm(self.link.fault)
            result = self.control.output(now)
        if self.link.fault_snapshot:
            self.last_fault_snapshot = self.link.fault_snapshot
        if self.link.ready(now) and self.link.state:
            if self.link.state.get("state_id") != self.last_encoder_state:
                self.encoder_rates.update(self.link.state.get("encoders"), self.link.last_rx)
                self.last_encoder_state = self.link.state.get("state_id")
        else:
            self.encoder_rates.invalidate()
        if self.onboard:
            oc = self.onboard.state()
            if not oc["fresh"] or not oc["state"] or not oc["state"]["mcu_enabled"]:
                result.update(left=0, right=0, legacy_drive_preview="0,0\n")
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
                                   **result, "monotonic_seconds": now,
                                   "simulation": ((self.onboard.state()["state"] or {}).get("mock") if self.onboard else not self.link.connected or self.mock is not None),
                                   "motor_transport": self.mode,
                                   "receipt_utc": datetime.now(timezone.utc).isoformat(),
                                   "receipt_monotonic_s": now, "input": dict(self.input), "input_seq": self.input_seq,
                                   "input_mode": self.input_mode,
                                   "browser_input": dict(self.browser_input), "last_valid_input_seq": self.last_valid_input_seq,
                                   "input_throttle": self.input["throttle"], "input_steering": self.input["steering"],
                                   "mode": self.mode, "operator_input_age_s": now-self.last_input,
                                   "control": result, "rover_state": self.link.state,
                                   "rover_diagnostics": self.link.diagnostics(now),
                                   "rover_first_fault": self.last_fault_snapshot,
                                   "onboard_state": self.onboard.state() if self.onboard else None,
                                   "onboard_request_preview": self.onboard_preview(result),
                                   "onboard_request": self.onboard_preview(result),
                                   "pose_model": dict(zip(("east_m", "north_m", "yaw_rad"), self.pose))}))
        self.file_log.submit("tick", self.records[-1])
        if self.sequence % 2 == 0:
            self.history.append({"t": now-self.started, "left": result["left"], "right": result["right"],
                                 "rtt": self.link.rtt_ms})
        if result["reason"] != self.previous_reason:
            self.previous_reason = result["reason"]
            self.event(result["reason"], "fault" if "timeout" in result["reason"].lower() or self.link.fault else "info")

    @property
    def mode(self):
        return self.onboard.mode if self.onboard else "mock" if self.mock else "udp" if self.link.connected else "model"

    def direct_enable_ready(self):
        # A delayed first HELLO reply can be fresh just before its original send
        # timestamp expires. Confirm non-motion command progress before offering
        # ARM; preserve the upstream 250/350 ms timeouts and require a new click.
        return (self.link.ready(self.clock()) and self.link.state is not None
                and not self.link.pending_arm and not self.link.disarm_pending
                and not self.link.state["enabled"] and not self.link.state["stopped"]
                and self.link.sent_ops.get(self.link.state["seq"]) not in (None, "HELLO"))

    def pwm_limit_max(self):
        if self.onboard: return .25  # Pinned ROS/onboard policy remains unchanged.
        return min(1.0,self.link.pwm_ceiling()/255) if self.link.connected else 1.0

    def onboard_preview(self, result):
        return {"session_id": self.video.session, "command_id": self.sequence, "enable_requested": result["enabled"],
                "stop_requested": result["stop_latched"], "forward_mps": round((result["left"]+result["right"])/2, 4),
                "turn_radps": round((result["right"]-result["left"])/.5, 4), "sent": False}

    def connection_status(self, now):
        blockers = []
        if not self.owner: blockers.append("Acquire browser control")
        remote = self.link.state or {}
        if self.control.stopped or remote.get("stopped"): blockers.append("Reset STOP and wait for confirmation")
        if self.link.fault: blockers.append(self.link.fault)
        elif self.link.connected and not self.direct_enable_ready():
            blockers.append("Wait for fresh command progress and confirmed disabled outputs")
        oc = None
        if self.onboard:
            oc = self.onboard.state()
            if not oc["fresh"] or not oc["owned"]: blockers.append("Wait for onboard feedback and Claim onboard control")
            feedback=oc["state"] or {}
            if not feedback.get("mcu_ready"): blockers.append("Wait for fresh disabled MCU feedback")
            if oc["fault"] or feedback.get("mcu_stopped") or feedback.get("stop_latched"):
                blockers.append("Reset onboard STOP and wait for confirmation")
        if self.input_mode == "gamepad" and not self.input_available: blockers.append("Gamepad unavailable; check controller mapping")
        if self.input_paused: blockers.append("Resume input; timeout test is paused")
        sample = self.control.samples[self.control.source]
        if now-sample.received >= self.control.timeout: blockers.append("Focus Drive & arm to provide fresh input")
        elif sample.throttle or sample.steering or sample.deadman: blockers.append("Center sticks and release drive hold")
        if self.input_mode == "rc-demo" and (self.link.connected or self.onboard): blockers.append("RC is preview-only; select virtual stick or gamepad")
        reset_ready = (not self.link.connected or (self.link.ready(now) and not remote.get("enabled")
                       and not self.link.pending_arm and not self.link.disarm_pending))
        if oc:
            feedback=oc["state"] or {}
            reset_ready=oc["fresh"] and oc["owned"] and feedback.get("mcu_ready") and not feedback.get("mcu_enabled") and not feedback.get("supervisor_enabled")
        return {"phase": self.link.phase(now) if not oc else "enabling" if self.control.armed and not (oc["state"] or {}).get("mcu_enabled") else "onboard",
                "enable_blockers": blockers, "can_enable": not blockers and not self.control.armed,
                "can_reset": bool(self.owner and reset_ready and (self.control.stopped or remote.get("stopped")
                                  or (oc and (oc["fault"] or (oc["state"] or {}).get("mcu_stopped")
                                              or (oc["state"] or {}).get("stop_latched"))))) }

    def state(self):
        now = self.clock()
        result = self.control.output(now)
        if self.link.connected and self.link.state:
            result["stop_latched"] = result["stop_latched"] or self.link.state["stopped"]
        fresh = self.gps.fresh(now) and self.gps_mode != "disconnected" and not self.gps_error
        oc = self.onboard.state() if self.onboard else None
        if oc and oc["state"]:
            result["stop_latched"] = result["stop_latched"] or oc["state"]["stop_latched"] or oc["state"]["mcu_stopped"]
            result["enabled"] = self.control.armed and oc["state"]["supervisor_enabled"]
            if not oc["fresh"] or not oc["state"]["mcu_enabled"]:
                result.update(left=0, right=0, legacy_drive_preview="0,0\n")
        return clean({
            "version": "0.2.0-NET5", "uptime_s": now-self.started, "sequence": self.sequence,
            "owner": self.owner, "clients": len(self.clients), "mode": self.mode,
            "input_mode": self.input_mode, "input": self.input, "input_age_s": now-self.last_input,
            "input_available": self.input_available, "browser_input": self.browser_input,
            "connection_status": self.connection_status(now), "rover_discovery": self.discovery.state(),
            "saved_rovers": self.profiles.state() | {"saving": bool(self.profile_task and not self.profile_task.done())},
            "input_paused": self.input_paused, "speed_limit": self.control.speed_limit,
            "speed_limit_max": self.pwm_limit_max(),
            "control": result, "arm_mode": self.control.arm_enabled, "joint": self.joint,
            "rover": {"connected": self.link.connected, "ready": self.link.ready(now),
                      "enable_ready": self.direct_enable_ready(),
                      "pending_enable": self.link.pending_arm is not None, "disarm_pending": self.link.disarm_pending, "fault": self.link.fault,
                      "state": self.link.state, "rtt_ms": self.link.rtt_ms, "rejected": self.link.rejected,
                      "age_s": now-self.link.last_rx, "mock_silent": self.mock.silent if self.mock else False},
            "diagnostics": self.link.diagnostics(now), "first_fault": self.last_fault_snapshot,
            "fault_history_count": len(self.fault_history),
            "connection_summary": self.link.summary(now) if not oc else (oc["state"]["reason"] if oc["state"] else "Waiting for onboard state"),
            "connection_degraded": self.link.degraded,
            "mock_options": {"reply_delay_ms": self.mock.reply_delay*1000 if self.mock else 0,
                             "drop_commands": self.mock.drop_commands if self.mock else False},
            "encoders": {"counts": (self.link.state or {}).get("encoders") or [None]*4,
                         "rates": self.encoder_rates.rates, "rate_valid": self.encoder_rates.valid,
                         "fresh": self.link.ready(now)},
            "onboard": oc, "ros2_available": ros_available(), "video_priorities": self.video.state(),
            "onboard_request_preview": self.onboard_preview(result),
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
            "file_logging": self.file_log.state() | {"configuring": bool(self.log_task and not self.log_task.done())},
            "capabilities": {"arm": "preview", "battery": "unavailable", "odometry": "model", "ros2": "available" if ros_available() else "runtime unavailable"},
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
        self.video.start()
        self.task = asyncio.create_task(self.run())

    async def close(self):
        self.running = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.disconnect()
        self.video.close()
        await self.discovery.close()
        if self.profile_task:
            await asyncio.gather(self.profile_task,return_exceptions=True)
        await self.gps_input.close()
        tasks = [c["task"] for c in self.cameras.values() if c["task"]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.log_task:
            await asyncio.gather(self.log_task, return_exceptions=True)
        await asyncio.to_thread(self.file_log.stop, "Backend shutdown")
