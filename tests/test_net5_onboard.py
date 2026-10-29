import asyncio
import time

import pytest

from c2_web.runtime import Runtime


async def wait_until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.02)


async def test_net5_idle_degradation_recovers_without_arm_and_active_fault_is_captured():
    r = Runtime()
    r.register("a")
    await r.start()
    try:
        await r.action("a", "connect", {"mode": "mock"})
        await wait_until(lambda: r.link.ready(r.clock()))
        r.mock.silent = True
        await asyncio.sleep(.45)
        assert r.link.degraded and not r.link.fault and not r.mock.enabled
        r.mock.silent = False
        await wait_until(lambda: r.link.ready(r.clock()))
        assert not r.control.armed
        await r.action("a", "input", {"seq": 1})
        await r.action("a", "enable", {})
        await wait_until(lambda: r.mock.enabled)
        r.mock.drop_commands = True
        for seq in range(2, 17):
            await r.action("a", "input", {"seq": seq, "throttle": .4, "deadman": True})
            await asyncio.sleep(.05)
        assert r.link.fault and r.last_fault_snapshot
        assert "acknowledged_command_age_ms" in r.last_fault_snapshot
        assert not r.control.armed and r.mock.throttle == 0
        assert any(row["rover_first_fault"] for row in r.records)
    finally:
        await r.close()


async def test_browser_keeps_neutral_input_fresh_during_delayed_enable():
    r = Runtime()
    r.register("a")
    await r.start()
    try:
        await r.action("a", "connect", {"mode": "mock"})
        await r.action("a", "mock_options", {"reply_delay_ms": 150, "drop_commands": False})
        await wait_until(lambda: r.direct_enable_ready() and r.link.rtt_ms is not None and r.link.rtt_ms >= 140)
        await r.action("a", "input", {"seq": 1})
        await r.action("a", "enable", {})
        for seq in range(2, 15):
            await r.action("a", "input", {"seq": seq})
            await asyncio.sleep(.04)
        assert not r.link.fault and r.mock.enabled and not r.link.pending_arm
        assert r.mock.throttle == 0
    finally:
        await r.close()


async def test_oc_loopback_claim_enable_release_stop_and_input_expiry_use_upstream_bridge():
    r = Runtime()
    r.register("a")
    await r.start()
    try:
        await r.action("a", "connect", {"mode": "oc-mock"})
        await wait_until(lambda: r.onboard.node.state is not None and r.onboard.node.state.mcu_ready)
        with pytest.raises(ValueError, match="Claim"):
            await r.action("a", "input", {"seq": 0})
            await r.action("a", "enable", {})
        await r.action("a", "onboard_claim", {})
        await wait_until(r.onboard.owned)
        await r.action("a", "input", {"seq": 1})
        await r.action("a", "speed_limit", {"value": .1})
        await r.action("a", "enable", {})
        for seq in range(2, 14):
            await r.action("a", "input", {"seq": seq, "throttle": 1, "deadman": True})
            await asyncio.sleep(.04)
        mock = r.onboard.node.bridge.mock
        assert mock.enabled and 0 < mock.throttle <= 26
        await r.action("a", "input", {"seq": 15, "throttle": 1, "deadman": False})
        await wait_until(lambda: mock.throttle == 0)
        await r.action("a", "input", {"seq": 16, "throttle": 1, "deadman": True})
        await wait_until(lambda: mock.throttle > 0)
        await asyncio.sleep(.35)  # The backend keeps ticking; it must NOT replay input.
        assert not r.control.armed and not mock.enabled and mock.throttle == 0
        await r.action("a", "input", {"seq": 17, "throttle": 1, "deadman": True})
        assert not r.control.armed
        await r.action("a", "stop", {})
        await wait_until(lambda: r.onboard.node.state.mcu_stopped and not r.onboard.node.state.mcu_enabled)
        assert r.onboard.records and all(not v for v in r.onboard.node.state.encoder_valid)
        await r.action("a", "reset_stop", {})
        await wait_until(lambda: not mock.stopped)
        assert not r.control.armed
    finally:
        await r.close()


async def test_initial_hello_cannot_offer_arm_before_nonmotion_command_progress():
    r = Runtime()
    r.register("a")
    try:
        await r.action("a", "connect", {"mode": "mock"})
        now = r.clock()
        # Valid fresh initial feedback, before the first post-handshake PING ACK.
        r.link.state = {"seq": 1, "epoch": 2, "enabled": False, "stopped": False}
        r.link.last_rx = now
        r.link.sent[1] = now
        assert r.link.ready(now) and not r.direct_enable_ready()
        await r.action("a", "input", {"seq": 1})
        with pytest.raises(ValueError, match="post-handshake"):
            await r.action("a", "enable", {})
        assert not r.control.armed and "ARM" not in r.link.sent_ops.values()
        r.link.send("PING", now=now)
        r.link.state["seq"] = r.link.seq
        assert r.direct_enable_ready()
        assert not r.control.armed  # Confirmation itself never enables.
    finally:
        await r.close()
