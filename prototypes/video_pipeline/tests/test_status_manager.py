import pytest

from status_manager import BandwidthInput, FeedPriorities, StatusManager

IDS = tuple(f"cam-{i:02}" for i in range(1, 6))


def priority(order=IDS, count=3, seq=1, session="c2", revision=1):
    return FeedPriorities(session, seq, revision, order, count)


def test_ranked_and_omitted_are_explicit_and_bandwidth_does_not_allocate():
    core = StatusManager(IDS)
    assert not core.snapshot()["inputs_ready"]
    core.receive_priorities(priority(order=("cam-03", "cam-01", "cam-05", "cam-04", "cam-02")))
    core.receive_bandwidth(BandwidthInput("estimator", 1, 0))
    result = core.snapshot()
    assert result["ranked_stream_ids"] == ["cam-03", "cam-01", "cam-05"]
    assert result["omitted_stream_ids"] == ["cam-04", "cam-02"]
    assert result["available_bandwidth_bps"] == 0
    assert result["inputs_ready"]
    assert not any(key in result for key in ("bitrates", "encoder", "selected_streams"))


@pytest.mark.parametrize("count", [0, 5])
def test_all_omitted_and_all_enabled(count):
    core = StatusManager(IDS)
    core.receive_priorities(priority(count=count))
    state = core.snapshot()
    assert state["ranked_stream_ids"] == list(IDS[:count])
    assert state["omitted_stream_ids"] == list(IDS[count:])


@pytest.mark.parametrize("order,count", [
    (IDS[:4], 3), (("cam-01",)*5, 3), (IDS[:4]+("unknown",), 3),
    (IDS, True), (IDS, -1), (IDS, 6), (IDS, 2.5), (IDS[:4]+(["cam-05"],), 3),
])
def test_invalid_priorities_do_not_mutate_received_inputs(order, count):
    core = StatusManager(IDS)
    core.receive_priorities(priority())
    before = core.snapshot()["output_sequence"]
    with pytest.raises(ValueError):
        core.receive_priorities(priority(order, count, seq=2))
    assert core.snapshot()["output_sequence"] == before
    assert core.snapshot()["ranked_stream_ids"] == list(IDS[:3])


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 2.5, "1000", 10_000_000_001])
def test_invalid_bandwidth_is_rejected(value):
    with pytest.raises(ValueError):
        StatusManager(IDS).receive_bandwidth(BandwidthInput("link", 1, value))


def test_stale_and_duplicate_samples_never_refresh_receipt_time_or_change_order():
    clock = [10.0]
    core = StatusManager(IDS, clock=lambda: clock[0])
    core.receive_priorities(priority(seq=2))
    core.receive_bandwidth(BandwidthInput("link", 2, 10000))
    clock[0] += 3.1
    assert not core.receive_priorities(priority(seq=1, count=0))
    assert not core.receive_bandwidth(BandwidthInput("link", 2, 0))
    state = core.snapshot()
    assert state["priorities_stale"] and state["bandwidth_stale"]
    assert state["ranked_stream_ids"] == list(IDS[:3])
    assert state["available_bandwidth_bps"] == 10000
    assert state["priority_age_s"] == pytest.approx(3.1)


def test_retired_session_cannot_override_new_session():
    core = StatusManager(IDS)
    core.receive_priorities(priority(session="old", seq=100))
    core.receive_priorities(priority(session="new", seq=1, count=1))
    assert not core.receive_priorities(priority(session="old", seq=101))
    assert core.snapshot()["priority_session"] == "new"
    assert core.snapshot()["enabled_count"] == 1


def test_wire_schema_round_trip_and_boolean_version_rejected():
    original = priority()
    assert FeedPriorities.from_dict(original.to_dict()) == original
    with pytest.raises(ValueError):
        FeedPriorities.from_dict(original.to_dict()|{"schema_version": True})


def test_ros2_output_contract_matches_core_snapshot_fields():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1]/"ros2/urc_video_interfaces/msg/StatusInputs.msg"
    fields = {line.split("#")[0].split()[-1] for line in path.read_text().splitlines()
              if line.split("#")[0].strip()}
    assert fields == set(StatusManager(IDS).snapshot())
