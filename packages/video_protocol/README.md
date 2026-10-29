# Shared video framing

`urc_video_protocol` is the standard-library-only URV1/URB1 contract used by the
prototype sender and the C2 receiver. Their separate locked Python environments
install this package through repository-relative editable paths. Do not install
an unrelated package from a registry with the same name or duplicate the serializer.

The canonical source is `urc_video_protocol/__init__.py`. Compatibility imports remain
at `c2_web/video_wire.py` and `prototypes/video_pipeline/video_wire.py`; those files
contain no framing implementation. See [the component map](../../docs/VIDEO_SYSTEM.md).

## URV1: TCP record

Network byte order, `HEADER = !4sII` (12 bytes), `META = !BBHH16sQQQQQI` (66 bytes),
then one H.264 Annex B access unit. Header fields are magic `URV1`, metadata length
and payload length. The fixed metadata order is:

| Field | Type/unit |
| --- | --- |
| Camera index | uint8, 1–5 (`Camera 01`–`05`) |
| Flags | uint8, bit 0 = IDR, bit 1 = declared same-host monotonic clock scope |
| Width, height | uint16 each, actual output pixels |
| Encoder session | 16 raw UUID bytes; a new session on format/worker replacement |
| Access-unit sequence | uint64, strictly increasing within a session |
| PTS | uint64 microseconds, normalized relative encoder time |
| Source sequence | uint64; zero means unavailable |
| Source receipt timestamp | uint64 monotonic nanoseconds; zero means unavailable |
| Sender timestamp | uint64 monotonic nanoseconds; zero means unavailable |
| Requested plan revision | uint32; zero means unavailable |

Sequences/PTS are bounded to JavaScript's safe integer range by validation. Output
dimensions are bounded to the current contract (16–3840 wide, 16–2160 high), and
payloads to 16 MiB. Read header lengths before allocating/reading a payload. This
application bound is separate from the sender's 4 MiB queue/unit policy.

The application overhead is 78 bytes per AU. It excludes TCP/IP/link headers and
ACK traffic. The stream is ordered TCP bytes, not one packet per frame. Do not
subtract monotonic timestamps across hosts without a declared clock mapping.

## URB1: browser message

The same 12-byte prefix uses magic `URB1`, bounded JSON metadata (at most 4096 bytes)
and unchanged H.264 bytes. The receiver adds a connection epoch, actual codec string
from SPS and its arrival time. Browser nanosecond clock fields are strings to avoid
precision loss; PTS microseconds remain safe integers. The receiver requires real
IDR/SPS/PPS at startup; the browser waits for a decodable keyframe on a new epoch.

Status/render/keyframe messages on the video WebSocket are separate JSON objects.
They never register an operator session or renew drive input freshness.

## Changes and tests

Run `uv run --frozen python scripts/verify.py` from the repository root. Tests cover
fragmentation, bad lengths/metadata, epochs and bounded queues; the prototype also
asserts both shims resolve to this same implementation. A new codec, framing layout,
camera count or cross-host time policy requires an explicit contract/version review
and coordinated sender, receiver, browser and test updates. Do not silently reinterpret
URV1/URB1 for a new hardware encoder.
