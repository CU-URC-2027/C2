"""Headless operator adapter for the upstream OC policy/ROS dashboard contract.

INPUT is published only from new browser input. This service's tick may pump
feedback and repeat STOP/DISARM, but never repeats a cached motion sample.
"""
from collections import deque
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"ros2_ws/src/urc_c2_chassis"))
from urc_c2_chassis.policy import CLAIM, INPUT, ENABLE, DISARM, STOP, RESET, Intent
from urc_c2_chassis.bridge import ChassisBridge


def ros_available():
    return importlib.util.find_spec("rclpy") is not None and importlib.util.find_spec("urc_c2_interfaces") is not None


class LoopbackOperator:
    def __init__(self):
        self.session = secrets.token_hex(16)
        self.sequence = 0
        self.bridge = ChassisBridge(mock=True)
        self.state, self.received = None, -float("inf")

    def pump(self):
        self.state = SimpleNamespace(**self.bridge.tick())
        self.received = time.monotonic()

    def fresh(self):
        return self.state is not None and time.monotonic()-self.received < .35

    def send(self, operation, throttle=0., steering=0., deadman=False):
        if not self.fresh():
            return False
        self.sequence += 1
        return self.bridge.receive(Intent(session=self.session, oc_boot=self.state.oc_boot,
            challenge=self.state.challenge, sequence=self.sequence, epoch=self.state.epoch,
            operation=operation, throttle=throttle, steering=steering, deadman=deadman))

    def close(self):
        self.bridge.close()


class ROSOperator:
    def __init__(self, namespace):
        if not ros_available():
            raise ValueError("ROS 2 and built urc_c2_interfaces are unavailable in this Python environment. Use the OC loopback mode on this Mac.")
        import rclpy
        from urc_c2_chassis.ros_io import OperatorNode
        self.rclpy = rclpy
        self.owns_context = not rclpy.ok()
        if self.owns_context:
            rclpy.init()
        self.node = OperatorNode(namespace=namespace or None)

    def pump(self):
        self.rclpy.spin_once(self.node, timeout_sec=0)

    def __getattr__(self, name):
        return getattr(self.node, name)

    def close(self):
        self.node.destroy_node()
        if self.owns_context and self.rclpy.ok():
            self.rclpy.shutdown()


class OnboardOperator:
    def __init__(self, mode, namespace=""):
        if not isinstance(namespace, str) or len(namespace) > 160 or (namespace and not namespace.startswith("/")):
            raise ValueError("ROS namespace must be empty or start with /")
        self.mode, self.namespace = mode, namespace
        self.node = LoopbackOperator() if mode == "oc-mock" else ROSOperator(namespace)
        self.permit = self.fault = self.had_feedback = False
        self.pending_stop = DISARM
        self.last_boot = ""
        self.last_input = -float("inf")
        self.sample = (0., 0., False)
        self.records = deque(maxlen=6000)

    def owned(self):
        return self.node.fresh() and self.node.state.owner_session == self.node.session

    def disarm(self, latch=False):
        self.permit = False
        if latch or self.pending_stop == STOP:
            self.pending_stop = STOP
        else:
            self.pending_stop = DISARM
        if self.owned():
            self.node.send(self.pending_stop)

    def command(self, operation, sample=(0., 0., False)):
        t, s, held = sample
        if operation == CLAIM:
            self.permit = False
            self.pending_stop = DISARM
            if not self.node.send(CLAIM):
                raise ValueError("Claim refused or no fresh onboard feedback")
            return
        if not self.owned():
            raise ValueError("Need fresh onboard feedback and Claim onboard control first")
        state = self.node.state
        if operation == ENABLE:
            if self.fault:
                raise ValueError("Feedback interruption: Reset STOP before enabling")
            if abs(t) >= .08 or abs(s) >= .08 or held or time.monotonic()-self.last_input >= .25:
                raise ValueError("Need fresh neutral input and released hold")
            if not state.mcu_ready or state.mcu_enabled or state.mcu_stopped:
                raise ValueError("Need fresh disabled MCU and cleared STOP")
            if not self.node.send(ENABLE, t, s, held):
                raise ValueError("Onboard Enable request was not accepted/published")
            self.pending_stop, self.permit = None, True
        elif operation == RESET:
            if state.supervisor_enabled or state.mcu_enabled or not state.mcu_ready:
                raise ValueError("Reset needs confirmed disabled MCU feedback")
            if not self.node.send(RESET):
                raise ValueError("Reset was not accepted/published")
            self.fault, self.permit, self.pending_stop = False, False, DISARM

    def input(self, throttle, steering, held, speed_limit=.25):
        self.last_input = time.monotonic()
        self.sample = (throttle, steering, held)
        if not self.owned():
            return
        if self.pending_stop == STOP:
            self.node.send(STOP)
        elif self.pending_stop == DISARM and (self.node.state.supervisor_enabled or self.node.state.mcu_enabled):
            self.node.send(DISARM)
        else:
            # The upstream OC applies a fixed 25% cap; retain the browser's
            # optional lower cap without ever increasing the OC request.
            scale = speed_limit/.25
            self.node.send(INPUT, throttle*scale, steering*scale, bool(held and self.permit))

    def tick(self):
        self.node.pump()
        if not self.node.fresh():
            if self.had_feedback:
                self.fault = True
                self.disarm(latch=True)
            return
        state = self.node.state
        if self.last_boot and state.oc_boot != self.last_boot:
            self.fault = True
            self.disarm(latch=True)
        self.last_boot, self.had_feedback = state.oc_boot, True
        if self.permit and time.monotonic()-self.last_input >= .25:
            self.disarm()
        if self.owned() and (self.pending_stop == STOP or (self.pending_stop == DISARM and (state.supervisor_enabled or state.mcu_enabled))):
            self.node.send(self.pending_stop)
        self.records.append({"receipt_utc": datetime.now(timezone.utc).isoformat(),
            "receipt_monotonic_s": time.monotonic(), "source": getattr(self, "source_label", "browser"),
            "throttle": self.sample[0], "steering": self.sample[1], "hold": self.sample[2],
            "state": self.state()["state"]})

    def state(self):
        fresh = self.node.fresh()
        state = self.node.state
        if state is not None:
            values = vars(state) if isinstance(state, SimpleNamespace) else {key: getattr(state, key) for key in state.get_fields_and_field_types()}
            values = {key: value if isinstance(value, (str, int, float, bool)) else list(value) for key, value in values.items()}
        else:
            values = None
        return {"mode": self.mode, "namespace": self.namespace, "fresh": fresh, "owned": self.owned(),
                "session": self.node.session, "permit": self.permit, "fault": self.fault,
                "pending_stop": self.pending_stop, "state": values, "capture_rows": len(self.records)}

    def close(self):
        self.disarm(latch=True)
        self.node.close()
