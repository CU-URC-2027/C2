"""Onboard ownership and input lease, independent of ROS for deterministic tests."""
from collections import deque
from dataclasses import dataclass
import math
import secrets
from .vendor.core import Control

CLAIM, INPUT, ENABLE, DISARM, STOP, RESET = range(6)


@dataclass
class Intent:
    version: int = 1
    session: str = ""
    oc_boot: str = ""
    challenge: str = ""
    sequence: int = 0
    epoch: int = 0
    operation: int = INPUT
    throttle: float = 0.0
    steering: float = 0.0
    deadman: bool = False


class Supervisor:
    """Receiver-issued, short-lived challenges bound transport delay without
    subtracting clocks on different PCs. This is freshness, NOT authentication.
    """
    def __init__(self):
        self.boot = secrets.token_hex(16)
        self.challenges = deque(maxlen=8)
        self.owner = ""
        self.sequence = 0
        self.epoch = 1
        self.last_owner = -math.inf
        self.control = Control()
        self.reason = "No operator owner; disabled"
        self.rejected = 0

    def challenge(self, now):
        if not self.challenges or now-self.challenges[-1][1] >= .1:
            self.challenges.append((secrets.token_hex(8), now))
        return self.challenges[-1][0]

    def disable(self, reason, latch=False):
        if self.control.armed or (latch and not self.control.stopped):
            self.epoch += 1
        if latch:
            self.control.stop(reason)
        else:
            self.control.disarm(reason)
        self.reason = reason

    def tick(self, now):
        if self.control.armed and now-self.control.samples["Xbox"].received >= .25:
            self.disable("Operator input expired; neutral Enable required")
        return self.control.output(now)

    def receive(self, intent, now, link_ready, mcu_enabled, mcu_stopped):
        self.tick(now)  # Never let recovered traffic conceal an expired lease.
        p = intent
        valid = (p.version == 1 and type(p.sequence) is int and 0 < p.sequence < 2**64
                 and type(p.epoch) is int and 0 <= p.epoch < 2**64
                 and p.operation in range(6) and type(p.deadman) is bool
                 and len(p.session) == 32 and all(c in "0123456789abcdef" for c in p.session)
                 and p.oc_boot == self.boot
                 and any(p.challenge == token and 0 <= now-issued < .25 for token, issued in self.challenges)
                 and all(type(v) in (int, float) and math.isfinite(v) and -1 <= v <= 1
                         for v in (p.throttle, p.steering)))
        if not valid:
            self.rejected += 1
            return False
        if p.operation == CLAIM and p.session != self.owner:
            if self.control.armed or mcu_enabled or (self.owner and now-self.last_owner < 1):
                self.rejected += 1
                return False
            if p.throttle or p.steering or p.deadman:
                return False
            self.owner, self.sequence = p.session, 0
            self.epoch += 1
            self.disable("Operator claimed; neutral Enable required")
        if p.session != self.owner or p.sequence <= self.sequence:
            self.rejected += 1
            return False
        if p.operation in (INPUT, ENABLE, RESET) and p.epoch != self.epoch:
            self.rejected += 1
            return False
        if p.operation == INPUT:
            self.control.receive("Xbox", p.throttle, p.steering, p.deadman, now)
        elif p.operation == ENABLE:
            if not link_ready or mcu_enabled or mcu_stopped or self.control.armed:
                self.reason = "Enable refused: need fresh, disabled MCU and cleared STOP"
                return False
            self.control.receive("Xbox", p.throttle, p.steering, p.deadman, now)
            accepted, reason = self.control.enable(now)
            self.reason = reason
            if not accepted:
                return False
        elif p.operation == DISARM:
            self.disable("Operator disarmed")
        elif p.operation == STOP:
            self.disable("Operator STOP", latch=True)
        elif p.operation == RESET:
            if self.control.armed or mcu_enabled or not link_ready:
                self.reason = "Reset refused: need fresh disabled MCU"
                return False
            self.control.reset_stop()
            self.epoch += 1
            self.reason = "STOP reset requested; wait for MCU confirmation"
        self.sequence, self.last_owner = p.sequence, now
        return True


class EncoderRates:
    """Unsigned pulse rate only; never invent direction or calibrated wheel speed."""
    def __init__(self):
        self.previous = None
        self.rates = [0.0]*4
        self.valid = [False]*4

    def update(self, counts, now):
        self.rates, self.valid = [0.0]*4, [False]*4
        counts = list(counts) if counts is not None else [None]*4
        if self.previous:
            old, stamp = self.previous
            dt = now-stamp
            if .005 <= dt <= .5:
                for i, (a, b) in enumerate(zip(old, counts)):
                    if a is None or b is None:
                        continue
                    delta = (b-a) & 0xffffffff
                    # Treat a reset or implausible jump as missing, not huge speed.
                    if delta/dt <= 100000:
                        self.rates[i], self.valid[i] = delta/dt, True
        self.previous = counts, now

    def invalidate(self):
        self.previous = None
        self.rates, self.valid = [0.0]*4, [False]*4
