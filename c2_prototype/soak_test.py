"""Localhost-only sustained drive and fault recovery check. Never addresses hardware."""
import argparse
import json
import time
from mock_rover import MockRover
from rover_link import RoverLink


def run(seconds=30, delay_ms=80):
    rover, link = MockRover(), RoverLink()
    samples = []
    def pump(duration, enabled=False, throttle=0):
        end = time.monotonic()+duration
        while time.monotonic() < end:
            link.tick(dict(enabled=enabled, stop_latched=False,
                           legacy_drive_preview=f"{throttle},0\n"))
            samples.append(link.diagnostics(time.monotonic()))
            time.sleep(.01)
    try:
        rover.reply_delay = delay_ms/1000
        link.connect("127.0.0.1", rover.port)
        pump(.4)
        assert link.ready(time.monotonic()), "Handshake failed"
        link.request_enable(time.monotonic())
        pump(seconds, True, 30)
        assert link.fault is None and rover.enabled, link.fault
        pump(.3, True, 0)
        assert rover.throttle == 0, "Release did not command zero"
        rover.drop_commands = True
        pump(.6, True, 30)
        assert not rover.enabled and link.fault, "Loss did not stop/latch"
        rover.drop_commands = False
        pump(.3, True, 30)
        assert not rover.enabled, "Recovered packets restarted motion"
        link.close()
        pump(1.1)  # old ownership lease must expire
        link.connect("127.0.0.1", rover.port)
        pump(.4)
        assert link.ready(time.monotonic()) and not rover.enabled
        summary = dict(result="PASS", drive_seconds=seconds, injected_reply_delay_ms=delay_ms,
                       samples=len(samples), release_zero=True, loss_stops=True,
                       recovery_stays_disabled=True, reconnect=True)
        print(json.dumps(summary, indent=2))
        return summary
    finally:
        link.close()
        rover.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--delay-ms", type=float, default=80)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600 or not 0 <= args.delay_ms <= 150:
        parser.error("Use 1..3600 seconds and 0..150 ms reply delay")
    run(args.seconds, args.delay_ms)
