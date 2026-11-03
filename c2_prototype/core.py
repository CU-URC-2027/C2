"""Hardware-independent C2 model. Outputs are previews, never motor writes.

The same authority/timeout policy must ultimately run on the rover, not only PC.
"""
from dataclasses import dataclass
import math

SOURCES = ("Xbox", "RC")
JOINTS = ("base", "shoulder", "elbow", "wrist", "gripper")


def axis(value):
    value = float(value)
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError("Input must be finite and between -1 and 1")
    return 0.0 if abs(value) < 0.08 else value


def legacy_drive(throttle, steering, max_pwm=None):
    """Matthew's UDP payload; this function does NOT transmit it."""
    values = [float(throttle), float(steering)]
    if any(not math.isfinite(v) or not -1 <= v <= 1 for v in values):
        raise ValueError("Drive output must be finite and between -1 and 1")
    # The joystick dead zone is applied before speed limiting, not again here.
    raw = [v*255 for v in values]
    if max_pwm is not None:
        if type(max_pwm) is not int or not 0<=max_pwm<=255:
            raise ValueError("PWM cap must be an integer from 0 to 255")
        scale = max(1, sum(abs(v) for v in raw)/max_pwm) if max_pwm else 1
        raw = [v/scale for v in raw] if max_pwm else [0,0]
    quantized = [round(v) for v in raw]
    if max_pwm is not None and sum(abs(v) for v in quantized)>max_pwm:
        # Rounding both half-count axes upward can create 256 at full mixed
        # output. Remove the one-count excess from the larger rounding error.
        index = max(range(2), key=lambda i:abs(quantized[i])-abs(raw[i]))
        quantized[index] -= 1 if quantized[index]>0 else -1
    return f"{quantized[0]},{quantized[1]}\n"


@dataclass
class Sample:
    throttle: float = 0.0
    steering: float = 0.0
    deadman: bool = False
    received: float = -math.inf


class Control:
    timeout = 0.25

    def __init__(self):
        self.source = "Xbox"
        self.samples = {name: Sample() for name in SOURCES}
        self.armed = False
        self.stopped = False
        self.reason = "Disarmed at startup"
        self.arm_enabled = False
        self.joint = "base"
        self.jog = 0.0
        self.jog_received = -math.inf
        self.speed_limit = 0.25

    def disarm(self, reason="Disarmed"):
        self.armed = False
        self.arm_enabled = False
        self.jog = 0.0
        self.reason = reason

    def stop(self, reason="Operator STOP"):
        self.stopped = True
        self.disarm(reason)

    def reset_stop(self):
        self.stopped = False
        self.disarm("STOP reset; enable again with neutral controls")

    def select(self, source):
        if source not in SOURCES:
            raise ValueError("Unknown control source")
        self.source = source
        self.disarm("Source changed; enable again")

    def receive(self, source, throttle, steering, deadman, now):
        if source not in SOURCES:
            raise ValueError("Unknown control source")
        # Check the old timestamp before refreshing it: a recovered stream must
        # not conceal a timeout and automatically restore motion.
        self.tick(now)
        try:
            self.samples[source] = Sample(axis(throttle), axis(steering), bool(deadman), now)
        except (ValueError, TypeError):
            if source == self.source:
                self.disarm("Invalid input")
            raise

    def enable(self, now):
        s = self.samples[self.source]
        if self.stopped:
            return False, "Reset STOP first"
        if now - s.received >= self.timeout:
            return False, "No fresh input"
        if s.throttle or s.steering or s.deadman:
            return False, "Center sticks and release drive hold first"
        self.armed = True
        self.reason = "Enabled; hold drive control to move"
        return True, self.reason

    def receive_jog(self, joint, rate, now):
        self.tick(now)
        if joint not in JOINTS:
            raise ValueError("Unknown joint")
        self.joint, self.jog, self.jog_received = joint, axis(rate), now

    def tick(self, now):
        if self.armed and now - self.samples[self.source].received >= self.timeout:
            self.disarm("Input timeout; enable again")
        if now - self.jog_received >= self.timeout:
            self.jog = 0.0

    def output(self, now):
        self.tick(now)
        s = self.samples[self.source]
        active = self.armed and not self.stopped and s.deadman
        # One task at a time for this first prototype: arm mode inhibits drive.
        throttle = s.throttle * self.speed_limit if active and not self.arm_enabled else 0.0
        steering = s.steering * self.speed_limit if active and not self.arm_enabled else 0.0
        left = max(-1, min(1, throttle + steering))
        right = max(-1, min(1, throttle - steering))
        # Cap each wheel as well as the requested throttle/steering.
        scale = max(1, max(abs(left), abs(right)) / self.speed_limit) if self.speed_limit else 1
        left, right = left / scale, right / scale
        throttle, steering = (left + right) / 2, (left - right) / 2
        rate = self.jog * 0.2 if self.armed and self.arm_enabled and not self.stopped else 0.0
        return {
            "source": self.source, "enabled": self.armed,
            "stop_latched": self.stopped, "left": left, "right": right,
            "legacy_drive_preview": legacy_drive(throttle, steering,max_pwm=round(self.speed_limit*255)),
            "arm_preview": {"type": "arm_jog", "joint": self.joint, "rate": rate},
            "reason": self.reason,
        }
