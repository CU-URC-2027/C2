"""Only onboard bridge owns motor UDP; usable without ROS in loopback tests."""
import time
from .policy import Supervisor, EncoderRates, ENABLE, DISARM, STOP, RESET
from .vendor.rover_link import RoverLink
from .vendor.mock_rover import MockRover


class ChassisBridge:
    def __init__(self, mock=True, host="", port=4210):
        self.gate = Supervisor()
        self.rates = EncoderRates()
        self.link = RoverLink()
        self.mock = MockRover() if mock else None
        self.mock_mode = bool(mock)
        if not mock and not host:
            raise ValueError("Real mode requires an explicit rover IPv4")
        try:
            self.link.connect("127.0.0.1" if mock else host, self.mock.port if mock else port)
        except Exception:
            self.close()
            raise
        self.last_mcu_state = -1
        self.state_sequence = 0

    def receive(self, intent, now=None):
        now = time.monotonic() if now is None else now
        state = self.link.state or {}
        accepted = self.gate.receive(intent, now, self.link.ready(now),
                                     state.get("enabled", False), state.get("stopped", False))
        if not accepted:
            return False
        try:
            if intent.operation == ENABLE:
                self.link.request_enable(now)
            elif intent.operation == DISARM:
                self.link.disable()
            elif intent.operation == STOP:
                self.link.disable(latch=True)
            elif intent.operation == RESET:
                self.link.reset_stop()
        except (ValueError, OSError) as exc:
            self.gate.disable(f"MCU transition refused: {exc}", latch=True)
            self.link.disable(latch=True)
        return True

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        result = self.gate.tick(now)
        self.link.tick(result, now)
        if self.link.fault:
            self.gate.disable(self.link.fault, latch=True)
        state = self.link.state or {}
        ready = self.link.ready(now)
        if ready and state.get("state_id") != self.last_mcu_state:
            self.rates.update(state.get("encoders"), self.link.last_rx)
            self.last_mcu_state = state["state_id"]
        elif not ready:
            self.rates.invalidate()
        counts = state.get("encoders") or [None]*4
        self.state_sequence += 1
        input_stamp = self.gate.control.samples["Xbox"].received
        return dict(version=1, oc_boot=self.gate.boot, challenge=self.gate.challenge(now),
                    owner_session=self.gate.owner, epoch=self.gate.epoch,
                    accepted_sequence=self.gate.sequence, state_sequence=self.state_sequence,
                    supervisor_enabled=self.gate.control.armed, stop_latched=self.gate.control.stopped,
                    mcu_ready=ready, mcu_enabled=ready and state.get("enabled", False),
                    mcu_stopped=state.get("stopped", False), mock=self.mock_mode,
                    reason=self.link.fault or self.gate.reason,
                    intent_age_s=now-input_stamp if input_stamp > 0 else -1.0,
                    mcu_age_s=now-self.link.last_rx if state else -1.0,
                    applied_throttle_pwm=state.get("throttle", 0), applied_steering_pwm=state.get("steering", 0),
                    encoder_counts=[0 if v is None else v for v in counts],
                    encoder_valid=[ready and v is not None for v in counts],
                    encoder_count_rate=self.rates.rates, encoder_rate_valid=self.rates.valid)

    def close(self):
        self.link.close()
        if self.mock:
            self.mock.close()
            self.mock = None
