"""Transport-independent input aggregator. Standard-library Python only.

This module validates priorities and available bandwidth and publishes a snapshot.
It never assigns bitrate, changes source generation, or chooses an encoder.
Adapters own network identity, serialization, delivery and publication.
"""
from dataclasses import dataclass
import time

SCHEMA_VERSION = 1


def uint(value, name, maximum=2**64-1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 0 to {maximum}")
    return value


def identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise ValueError("source_session must be a nonempty string of at most 80 characters")
    return value


@dataclass(frozen=True)
class FeedPriorities:
    source_session: str
    sequence: int
    revision: int
    ordered_stream_ids: tuple[str, ...]
    enabled_count: int
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, dict) or type(row.get("schema_version")) is not int or row.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported priority schema")
        order = row.get("ordered_stream_ids")
        if not isinstance(order, (list, tuple)) or not all(isinstance(s, str) for s in order):
            raise ValueError("ordered_stream_ids must be a list of stream IDs")
        return cls(identity(row.get("source_session")), uint(row.get("sequence"), "sequence"),
                   uint(row.get("revision"), "revision"), tuple(order),
                   uint(row.get("enabled_count"), "enabled_count", len(order)))

    def validate(self, stream_ids):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported priority schema")
        identity(self.source_session)
        uint(self.sequence, "sequence")
        uint(self.revision, "revision")
        uint(self.enabled_count, "enabled_count", len(stream_ids))
        if (not isinstance(self.ordered_stream_ids, tuple)
                or not all(isinstance(s, str) for s in self.ordered_stream_ids)
                or len(self.ordered_stream_ids) != len(stream_ids)
                or len(set(self.ordered_stream_ids)) != len(stream_ids)
                or set(self.ordered_stream_ids) != set(stream_ids)):
            raise ValueError("List every known stream exactly once, including omitted streams")

    def to_dict(self):
        return {"schema_version": self.schema_version, "source_session": self.source_session,
                "sequence": self.sequence, "revision": self.revision,
                "ordered_stream_ids": list(self.ordered_stream_ids), "enabled_count": self.enabled_count}


@dataclass(frozen=True)
class BandwidthInput:
    source_session: str
    sequence: int
    available_bps: int
    schema_version: int = SCHEMA_VERSION

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported bandwidth schema")
        identity(self.source_session)
        uint(self.sequence, "sequence")
        uint(self.available_bps, "available_bps", 10_000_000_000)


class StatusManager:
    def __init__(self, stream_ids, clock=time.monotonic, stale_after_s=3.0):
        self.stream_ids = tuple(stream_ids)
        if not self.stream_ids or len(set(self.stream_ids)) != len(self.stream_ids):
            raise ValueError("Stream IDs must be nonempty and unique")
        self.clock, self.stale_after_s = clock, stale_after_s
        self.priorities = self.bandwidth = None
        self.priority_received = self.bandwidth_received = None
        self.output_sequence = 0
        self.rejected = 0
        self.retired = {"priority": set(), "bandwidth": set()}

    def newer(self, channel, incoming, previous):
        if previous is None:
            return True
        if incoming.source_session == previous.source_session:
            return incoming.sequence > previous.sequence
        if incoming.source_session in self.retired[channel]:
            return False
        if len(self.retired[channel]) >= 32:
            raise ValueError("Too many input sessions; restart the adapter")
        self.retired[channel].add(previous.source_session)
        return True

    def receive_priorities(self, message):
        message.validate(self.stream_ids)
        if not self.newer("priority", message, self.priorities):
            self.rejected += 1
            return False
        self.priorities, self.priority_received = message, self.clock()
        self.output_sequence += 1
        return True

    def receive_bandwidth(self, message):
        message.validate()
        if not self.newer("bandwidth", message, self.bandwidth):
            self.rejected += 1
            return False
        self.bandwidth, self.bandwidth_received = message, self.clock()
        self.output_sequence += 1
        return True

    def snapshot(self):
        now = self.clock()
        p, b = self.priorities, self.bandwidth
        age_p = now-self.priority_received if p else None
        age_b = now-self.bandwidth_received if b else None
        order = list(p.ordered_stream_ids) if p else []
        count = p.enabled_count if p else 0
        return {"schema_version": SCHEMA_VERSION, "output_sequence": self.output_sequence,
                "priorities_received": p is not None, "bandwidth_received": b is not None,
                "inputs_ready": p is not None and b is not None,
                "ordered_stream_ids": order, "enabled_count": count,
                "ranked_stream_ids": order[:count], "omitted_stream_ids": order[count:],
                "available_bandwidth_bps": b.available_bps if b else None,
                "priority_session": p.source_session if p else None,
                "priority_sequence": p.sequence if p else None,
                "priority_revision": p.revision if p else None,
                "bandwidth_session": b.source_session if b else None,
                "bandwidth_sequence": b.sequence if b else None,
                "priority_age_s": age_p, "bandwidth_age_s": age_b,
                "priorities_stale": age_p is None or age_p > self.stale_after_s,
                "bandwidth_stale": age_b is None or age_b > self.stale_after_s,
                "stale_after_s": self.stale_after_s, "rejected_messages": self.rejected}
