import asyncio
import json
import threading

import pytest

from c2_web.file_logging import DiagnosticLog
from c2_web.runtime import Runtime


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_logging_is_opt_in_unique_and_flushes_on_stop(tmp_path):
    from pathlib import Path
    log = DiagnosticLog()
    log.submit("tick", {"no_file": True})
    assert not log.state()["enabled"] and list(tmp_path.iterdir()) == []
    folder = tmp_path / "user chosen folder"
    folder.mkdir()
    log.start(str(folder), {"mode": "model"})
    path = Path(log.path)
    log.submit("tick", {"input_seq": 1, "left": 0})
    log.submit("event", {"text": "Rover connected"})
    log.stop()
    content = rows(path)
    assert [r["type"] for r in content] == ["session_start", "tick", "event", "session_end"]
    assert content[0]["initial"]["mode"] == "model"
    assert all(r["utc"].endswith("+00:00") for r in content)
    assert not log.state()["enabled"] and not log.state()["stopping"]
    assert log.state()["bytes_written"] == path.stat().st_size
    original = path.read_bytes()
    log.start(str(folder), {})
    assert log.path != str(path)
    log.stop("Backend shutdown")
    assert path.read_bytes() == original
    assert rows(Path(log.path))[-1]["reason"] == "Backend shutdown"


@pytest.mark.parametrize("destination", [None, "", "relative/folder", "missing", "file"])
def test_bad_destination_is_visible_without_creating_or_overwriting(tmp_path, destination):
    log = DiagnosticLog()
    if destination == "missing":
        destination = str(tmp_path / "does not exist")
    if destination == "file":
        file = tmp_path / "original.txt"
        file.write_text("preserve me")
        destination = str(file)
    with pytest.raises(ValueError):
        log.start(destination, {})
    assert not log.enabled and log.state()["error"]
    assert not list(tmp_path.glob("c2-diagnostics-*"))


def test_bounded_queue_reports_gaps_and_does_not_wait_for_disk(tmp_path, monkeypatch):
    from pathlib import Path
    entered, release = threading.Event(), threading.Event()
    log = DiagnosticLog(queue_limit=2)
    original = log._write_record
    def slow(stream, row):
        entered.set()
        assert release.wait(3)
        original(stream, row)
    monkeypatch.setattr(log, "_write_record", slow)
    log.start(str(tmp_path), {})
    try:
        assert entered.wait(1)
        for i in range(20):
            log.submit("tick", {"sequence": i})
        assert log.state()["queued_records"] <= 2 and log.state()["dropped_records"] >= 18
    finally:
        release.set()
        log.stop()
    saved = rows(Path(log.path))
    assert saved[0]["type"] == "session_start"
    assert any(row["type"] == "log_gap" for row in saved)
    assert saved[-1]["dropped_records_total"] >= 18


def test_disk_failure_turns_logging_off_and_preserves_error(tmp_path, monkeypatch):
    log = DiagnosticLog()
    def fail(*args):
        raise OSError("disk full for test")
    monkeypatch.setattr(log, "_write_record", fail)
    log.start(str(tmp_path), {})
    log._thread.join(timeout=1)
    assert not log.enabled and "disk full" in log.error
    log.submit("tick", {"after_error": True})  # Never raises into the control loop.
    log.stop()


def test_unwritable_folder_is_reported_without_enabling(tmp_path, monkeypatch):
    import c2_web.file_logging as module
    def denied(*args):
        raise PermissionError("folder is read-only for test")
    monkeypatch.setattr(module.os, "open", denied)
    log = DiagnosticLog()
    with pytest.raises(ValueError, match="read-only"):
        log.start(str(tmp_path), {})
    assert not log.enabled and log.error


async def wait_for(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.02)


async def test_slow_start_does_not_block_operator_samples_or_create_freshness(tmp_path, monkeypatch):
    r = Runtime()
    r.register("operator")
    entered, release = threading.Event(), threading.Event()
    original = r.file_log.start
    def slow(*args):
        entered.set()
        assert release.wait(3)
        original(*args)
    monkeypatch.setattr(r.file_log, "start", slow)
    try:
        await r.action("operator", "file_logging", {"enabled": True, "directory": str(tmp_path)})
        await wait_for(entered.is_set)
        assert r.state()["file_logging"]["configuring"]
        await r.action("operator", "input", {"seq": 0})
        await r.action("operator", "enable", {})
        await r.action("operator", "input", {"seq": 1, "throttle": .5, "deadman": True})
        assert r.control.output(r.clock())["left"] > 0
        old_input = r.last_input
        await asyncio.sleep(.27)
        r.tick()
        assert not r.control.armed and r.last_input == old_input
    finally:
        release.set()
        await r.close()


async def test_runtime_records_failed_connect_enable_and_fault_without_unrelated_content(tmp_path):
    from pathlib import Path
    r = Runtime()
    r.register("operator")
    r.register("viewer")
    await r.start()
    try:
        with pytest.raises(ValueError, match="view-only"):
            await r.action("viewer", "file_logging", {"enabled": True, "directory": str(tmp_path)})
        assert list(tmp_path.iterdir()) == []
        await r.action("operator", "file_logging", {"enabled": True, "directory": str(tmp_path)})
        await r.log_task
        assert r.file_log.enabled
        with pytest.raises(ValueError):
            await r.action("operator", "connect", {"mode": "udp", "host": "not an IP", "port": 4210})
        with pytest.raises(ValueError):
            await r.action("operator", "gps_compare", {"content": "DO_NOT_INCLUDE_THIS_CONTENT"})
        await r.action("operator", "connect", {"mode": "mock"})
        await wait_for(r.direct_enable_ready)
        await r.action("operator", "input", {"seq": 1, "throttle": .5})
        with pytest.raises(ValueError, match="Center sticks"):
            await r.action("operator", "enable", {})
        await r.action("operator", "input", {"seq": 2})
        await r.action("operator", "enable", {})
        for seq in range(3, 10):
            await r.action("operator", "input", {"seq": seq, "throttle": .5, "deadman": True})
            await asyncio.sleep(.04)
        assert r.mock.throttle > 0
        await r.action("operator", "mock_silent", {})
        for seq in range(10, 22):
            await r.action("operator", "input", {"seq": seq, "throttle": .5, "deadman": True})
            await asyncio.sleep(.04)
        assert r.link.fault and not r.control.armed
        await r.action("operator", "file_logging", {"enabled": False})
        await r.log_task
        saved = rows(Path(r.file_log.path))
        assert any(row["type"] == "action_rejected" and row["data"]["action"] == "connect" for row in saved)
        ticks = [row["data"] for row in saved if row["type"] == "tick"]
        assert any(row["rover_first_fault"] for row in ticks)
        assert any(row["rover_state"] and row["rover_state"]["throttle"] > 0 for row in ticks)
        assert all("input_seq" in row and "rover_diagnostics" in row for row in ticks)
        assert "DO_NOT_INCLUDE_THIS_CONTENT" not in Path(r.file_log.path).read_text()
        assert saved[-1]["type"] == "session_end"
    finally:
        await r.close()


async def test_invalid_folder_failure_does_not_kill_runtime(tmp_path):
    r = Runtime()
    r.register("operator")
    try:
        await r.action("operator", "file_logging", {"enabled": True, "directory": str(tmp_path / "missing")})
        await r.log_task
        assert r.state()["file_logging"]["error"] and not r.file_log.enabled
        await r.action("operator", "input", {"seq": 0})
        r.tick()
        assert r.sequence == 1
    finally:
        await r.close()
