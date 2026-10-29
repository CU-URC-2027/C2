import json
import socket
import time

import pytest

from c2_web.priorities import STREAM_IDS, VideoPriorities


def test_actual_udp_publication_ack_and_edit_revision():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1)
    publisher = VideoPriorities(enabled=True)
    publisher.destination("127.0.0.1", receiver.getsockname()[1], True)
    publisher.start()
    try:
        publisher.update(list(STREAM_IDS[::-1]), 2, 1)
        publisher.tick()
        body, peer = receiver.recvfrom(4096)
        row = json.loads(body)
        assert row["publisher"]["service"] == "urc-c2-web" and row["publisher"]["pid"] > 0
        data = row["data"]
        assert data["ordered_stream_ids"][:2] == ["cam-05", "cam-04"]
        assert data["enabled_count"] == 2 and data["revision"] == 2
        receiver.sendto(json.dumps({"type": "priority_ack", "source_session": data["source_session"],
            "sequence": data["sequence"], "revision": data["revision"]}).encode(), peer)
        for _ in range(30):
            publisher.tick()
            if publisher.ack_revision == 2:
                break
            time.sleep(.01)
        assert publisher.state()["receiver_fresh"] and publisher.ack_revision == 2
        with pytest.raises(ValueError):
            publisher.update(list(STREAM_IDS), 5, 1)
        with pytest.raises(ValueError):
            publisher.update(["cam-01"]*5, 2, 2)
    finally:
        publisher.close()
        receiver.close()


def test_local_receiver_boundary_and_explicit_omissions():
    p = VideoPriorities(enabled=False)
    for count in (0, 5):
        p.update(list(STREAM_IDS), count, p.revision)
        assert p.message()["enabled_count"] == count
    for host, port, enabled in (("192.168.1.1", 8873, True), ("127.0.0.1", True, True), ("127.0.0.1", 8873, "yes")):
        with pytest.raises(ValueError):
            p.destination(host, port, enabled)
