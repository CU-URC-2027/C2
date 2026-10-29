import asyncio
import math

import pytest

from c2_web.runtime import Runtime, number


class Clock:
    value = 100.0
    def __call__(self):
        return self.value


def sample(seq=0, throttle=0, deadman=False):
    return dict(seq=seq, throttle=throttle, steering=0, deadman=deadman, jog=0)


async def test_stale_operator_input_cannot_be_renewed_by_tick_or_recovery():
    clock = Clock()
    r = Runtime(clock)
    r.register("operator")
    await r.action("operator", "input", sample())
    await r.action("operator", "enable", {})
    await r.action("operator", "input", sample(1, 1, True))
    assert r.state()["control"]["left"] == .25
    clock.value += .251
    r.tick()
    assert not r.control.armed
    assert r.state()["control"]["left"] == 0
    await r.action("operator", "input", sample(2, 1, True))
    assert not r.control.armed
    with pytest.raises(ValueError):
        await r.action("operator", "enable", {})
    await r.close()


async def test_owner_disconnect_stop_and_no_automatic_takeover():
    r = Runtime()
    r.register("a")
    r.register("b")
    with pytest.raises(ValueError, match="view-only"):
        await r.action("b", "enable", {})
    await r.action("a", "input", sample())
    await r.action("a", "enable", {})
    await r.action("b", "stop", {})
    assert r.control.stopped and not r.control.armed
    await r.action("a", "reset_stop", {})
    assert not r.control.stopped and not r.control.armed
    r.unregister("a")
    assert r.owner is None
    await r.action("b", "claim", {})
    assert r.owner == "b" and not r.control.armed
    with pytest.raises(ValueError, match="fresh"):
        await r.action("b", "enable", {})
    await r.close()


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "1", 1.1, None])
def test_numeric_commands_reject_nonfinite_and_out_of_range(bad):
    with pytest.raises(ValueError):
        number(bad)


async def test_duplicate_input_and_missing_gamepad():
    r = Runtime()
    r.register("a")
    await r.action("a", "input", sample())
    with pytest.raises(ValueError):
        await r.action("a", "input", sample())
    await r.action("a", "input_mode", {"mode": "gamepad"})
    await r.action("a", "input", sample(1))
    assert not r.control.armed
    with pytest.raises(ValueError, match="fresh"):
        await r.action("a", "enable", {})
    await r.close()


async def test_arm_preview_inhibits_drive_and_expires_jog():
    clock = Clock()
    r = Runtime(clock)
    r.register("a")
    await r.action("a", "input", sample())
    await r.action("a", "enable", {})
    await r.action("a", "arm_mode", {})
    await r.action("a", "input", sample(1, 1, True)|{"jog": 1})
    out = r.state()["control"]
    assert out["left"] == 0 and out["arm_preview"]["rate"] == .2
    clock.value += .251
    assert r.state()["control"]["arm_preview"]["rate"] == 0
    await r.close()


async def test_mock_handshake_drive_and_ack_loss_fail_closed():
    r = Runtime()
    r.register("a")
    await r.start()
    try:
        await r.action("a", "connect", {"mode": "mock"})
        for i in range(30):
            await r.action("a", "input", sample(i))
            await asyncio.sleep(.05)
            if r.direct_enable_ready():
                break
        assert r.link.ready(r.clock())
        assert not r.mock.enabled
        await r.action("a", "enable", {})
        for i in range(31, 42):
            await r.action("a", "input", sample(i, .8, True))
            await asyncio.sleep(.05)
        assert r.mock.enabled and r.mock.throttle > 0
        await r.action("a", "mock_silent", {})
        for i in range(50, 65):
            await r.action("a", "input", sample(i, .8, True))
            await asyncio.sleep(.05)
        assert r.link.fault and not r.control.armed
        assert r.mock.throttle == 0
    finally:
        await r.close()


async def test_gps_synthetic_and_reference_comparison():
    r = Runtime()
    r.register("a")
    await r.action("a", "gps_mode", {"mode": "demo"})
    r.tick()
    assert r.state()["gps"]["fresh"]
    assert r.gps.latitude is not None
    from c2_web.legacy import ROOT
    await r.action("a", "gps_compare", {"content": (ROOT/"c2_prototype/examples/gps_comparison.jsonl").read_text()})
    assert r.comparison["metrics"]["count"] > 0
    with pytest.raises(ValueError, match="Invalid comparison"):
        await r.action("a", "gps_compare", {"content": "[]\n"})
    await r.close()
