"""C2-owned video priorities and an optional local UDP publication adapter.

No source generation or encoding lives here. The receiver is independently run;
the C2 backend publishes configuration even when its browser is closed. This
configuration heartbeat never refreshes a chassis operator-input timestamp.
"""
import ipaddress
import json
import os
import socket
import time
import uuid

STREAM_IDS = tuple(f"cam-{i:02}" for i in range(1, 6))


class VideoPriorities:
    def __init__(self, clock=time.monotonic, enabled=None):
        self.clock = clock
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.revision = 1
        self.order, self.enabled_count = STREAM_IDS, len(STREAM_IDS)
        self.target = ("127.0.0.1", 8873)
        self.enabled = os.environ.get("C2_VIDEO_PRIORITIES_ENABLED", "1") == "1" if enabled is None else enabled
        self.socket = None
        self.last_sent = self.last_ack = None
        self.ack_sequence = self.ack_revision = None
        self.rtt_ms = None
        self.error = None
        self.sent = {}

    def update(self, order, enabled_count, expected_revision):
        if type(expected_revision) is not int or expected_revision != self.revision:
            raise ValueError("Video priorities changed; reload the current list before sending")
        if (not isinstance(order, list) or not all(isinstance(x, str) for x in order)
                or len(order) != len(STREAM_IDS) or set(order) != set(STREAM_IDS)):
            raise ValueError("List Camera 01–05 exactly once, including omitted feeds")
        if type(enabled_count) is not int or not 0 <= enabled_count <= len(STREAM_IDS):
            raise ValueError("Enabled count must be an integer from 0 to 5")
        self.order, self.enabled_count = tuple(order), enabled_count
        self.revision += 1
        self.last_sent = None

    def destination(self, host, port, enabled):
        try:
            address = ipaddress.IPv4Address(host)
        except (ValueError, TypeError) as exc:
            raise ValueError("Use a loopback IPv4 receiver for this local adapter") from exc
        if not address.is_loopback or type(port) is not int or not 1024 <= port <= 65535 or type(enabled) is not bool:
            raise ValueError("Use a loopback IPv4, port 1024–65535 and a Boolean enabled flag")
        self.target, self.enabled = (str(address), port), enabled
        self.last_sent = self.last_ack = None
        self.ack_revision = self.ack_sequence = None
        self.sent.clear()

    def start(self):
        if self.socket:
            return
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.setblocking(False)

    def message(self):
        return {"schema_version": 1, "source_session": self.session, "sequence": self.sequence,
                "revision": self.revision, "ordered_stream_ids": list(self.order),
                "enabled_count": self.enabled_count}

    def tick(self):
        now = self.clock()
        if not self.socket:
            return
        for _ in range(32):
            try:
                packet, address = self.socket.recvfrom(4096)
            except BlockingIOError:
                break
            except OSError as exc:
                self.error = f"Receiver unavailable ({type(exc).__name__})"
                break
            try:
                row = json.loads(packet)
                seq, revision = row.get("sequence"), row.get("revision")
                if (address != self.target or row.get("type") != "priority_ack"
                        or row.get("source_session") != self.session
                        or type(seq) is not int or seq not in self.sent
                        or type(revision) is not int or revision != self.sent[seq][1]
                        or (self.ack_sequence is not None and seq <= self.ack_sequence)):
                    continue
                self.ack_sequence, self.ack_revision, self.last_ack = seq, revision, now
                self.rtt_ms = (now-self.sent[seq][0])*1000
                self.error = None
            except (ValueError, AttributeError, TypeError, UnicodeError):
                continue
        if self.enabled and (self.last_sent is None or now-self.last_sent >= .5):
            self.sequence += 1
            body = json.dumps({"type": "feed_priorities", "data": self.message(),
                "publisher": {"service": "urc-c2-web", "pid": os.getpid()}}, allow_nan=False,
                separators=(",", ":")).encode()
            try:
                self.socket.sendto(body, self.target)
                self.sent[self.sequence] = (now, self.revision)
                self.sent = {seq: stamp for seq, stamp in self.sent.items() if seq > self.sequence-128}
                self.last_sent = now
            except OSError as exc:
                self.error = f"Priority publication failed ({type(exc).__name__})"

    def state(self):
        now = self.clock()
        return dict(self.message(), stream_names={key: f"Camera {i:02}" for i, key in enumerate(STREAM_IDS, 1)},
                    publisher_enabled=self.enabled, target=list(self.target),
                    local_address=list(self.socket.getsockname()) if self.socket else None,
                    receiver_fresh=self.last_ack is not None and now-self.last_ack < 3,
                    ack_sequence=self.ack_sequence, ack_revision=self.ack_revision,
                    ack_age_s=now-self.last_ack if self.last_ack is not None else None,
                    rtt_ms=self.rtt_ms, error=self.error, pid=os.getpid())

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None
