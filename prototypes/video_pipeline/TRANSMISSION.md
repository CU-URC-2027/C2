# Loopback video transmission

October 28, 2026. User-authorized local prototype. Actual path:

```text
Five raw source generators → hardware H.264 encoder → bounded OutputHub
  → Transmission (one TCP connection per active camera)
  → separate C2 Python process, TCP 127.0.0.1:8874
  → dedicated binary WebSocket per camera → browser WebCodecs → Camera 01–05
```

The C2 receiver relays the encoded bytes. It does not decode video, generate replacement frames or re-encode JPEGs. The architecture lab remains a visual/control surface for actual processes. This repository includes both components, with separate processes/environments and a shared protocol package. The prototype still binds to loopback and does not operate physical devices.

## Running it

1. Start C2 from the repository root (`../..`): `uv run python scripts/dev.py`. Its HTTP/browser service stays on `127.0.0.1:8870`; its passive video listener starts on `127.0.0.1:8874`. `C2_VIDEO_TCP_PORT` can select another port.
2. Start this lab with `uv run python dev.py`; open `http://127.0.0.1:8872`.
3. Enable **video streams**, **encoding**, then **transmission** on their respective nodes. All three workload controls start OFF after a lab restart. Transmission follows actual encoder sessions; it never implicitly starts a generator or encoder.
4. Open C2 at `http://127.0.0.1:8870/#cameras` and select **Start live video**. The target in-app browser was checked and supports WebCodecs/H.264. Unsupported browsers show a capability/configuration error; no hidden JPEG fallback is used.
5. Set feed ranking/omissions in the existing real C2 priority list. Its backend continues publishing priorities over the existing UDP path. The snapshot/demo camera controls are preserved below the new video view.

**Pause view**, switching away from Cameras, hiding the browser tab or stopping live video closes its video sockets and decoders and releases queued VideoFrames. It leaves C2 priorities and rover workload enablement independent. Stop transmission to release TCP senders; disable encoding and source generation to release those workloads. Closing the browser alone does not turn off enabled rover workloads.

The new Transmission node shows real process/destination information, shared allowance, TCP payload rate, per-camera queue depth/age, dropped frames, connections/reconnects, C2 PID, received FPS and browser-reported rendered FPS. ACK-derived live metrics require a recent connected acknowledgement. The encoder node and its optional diagnostic JPEG previews remain separate from this actual C2 playback path.

## Budget, delay and freshness

The video path is now actually byte-paced through one shared budget:

`TCP application-byte allowance = link bandwidth × video share`

Encoding Decision still targets **80% of that allowance**, retaining its existing 20% headroom. The sender counts its compact record headers along with the H.264 payload. No second 20% reduction is applied. Five connections share one token bucket; chunks waiting for it are ordered by the received C2 priority. This is application scheduling, not operating-system TCP priority or a hard guarantee of radio airtime.

The existing bandwidth/delay controls feed the actual video sender. Each frame becomes eligible after the configured one-way delay; byte pacing controls subsequent writes. The limiter is ahead of real TCP sockets, not just a displayed estimate. Its short token burst and keyframe bursts mean subsecond observations vary. The measured `wire_bitrate_bps` field counts **TCP application payload** (URV1 headers plus H.264), excluding IP/TCP/Ethernet headers and reverse ACK traffic. The UDP priority/ACK shaper still operates separately; this prototype does not simulate background comms load, NIC contention, packet loss/reordering, TCP retransmission delay or asymmetric radio behavior.

TCP retains ordered, reliable delivery. Each camera has its own connection to prevent one stream's queued bytes from directly holding the other streams behind it. It still shares the real physical bottleneck with the other connections. Once old bytes enter TCP they cannot be selectively removed from that connection; the sender closes/reconnects a stalled or over-age stream and resumes at a fresh IDR/SPS/PPS.

Sender queues are bounded to **8 access units / 4 MiB per camera**, with one in-flight record. A unit larger than the byte bound is rejected. Queued chains are discarded on sequence gaps/overflow and resume on an IDR. A **500 ms transmission-age deadline** is measured from availability of the encoded access unit, excluding prior capture/encoding time. Writes have a 400 ms drain timeout; missing application ACKs also trigger reconnection. Delays larger than the transmission deadline cannot produce usable video under this policy. These are prototype engineering values, not approved operational latency requirements.

Receiver-to-browser queues are bounded to **6 frames / 4 MiB per viewer**. A slow viewer is independently resynchronized or disconnected; it cannot grow an unbounded queue or stall the TCP receiver. Keyframe requests are debounced. Format/encoder changes and every new TCP connection have distinct epochs. New viewers wait for a valid IDR with SPS/PPS. Stopped/disconnected inputs clear queued output; browser overlays explicitly show unavailable/stale video.

Browser decoding is native WebCodecs with a hardware preference, configuration probing and no claimed guarantee of hardware selection. It exposes received, decoded and rendered rates separately. A short **80 ms PTS-based presentation buffer**, bounded to five decoded frames, smooths batched native decoder callbacks; overdue frames may be skipped. Rendering uses an appropriately sized canvas backing image (at most 960 pixels wide) while decoding the actual received resolution. This is not a lower-resolution re-encode. Resource pressure/browser scheduling can reduce rendered FPS below received/decoded FPS; the measurements remain visible.

Only the present same-host loopback mode compares Python monotonic source/receiver timestamps. Source receipt is not physical camera exposure. Browser arrival-to-render time is a separate client measurement. A receiver wall-clock timestamp rejects substantially delayed local browser deliveries. A two-computer or remotely hosted-browser test will need an explicit clock-mapping/uncertainty policy before claiming one-way source-to-screen latency.

## Protocol and files

- `transmission.py`: shared pacer, per-camera TCP owners, IDR-aware queues, deadlines, acknowledgements and reconnects.
- `video_wire.py`: compatibility imports from the canonical `../../packages/video_protocol/` standard-library package. C2 uses the same package; neither app imports the other process's objects.
- C2 `c2_web/video_receiver.py`: bounded TCP receive and viewer fanout. `c2_web/api.py` exposes `/api/live-video/state`, `/api/live-video/restart` and `/ws/video/cam-01` through `cam-05`.
- C2 `web/live-video.js` / `.css`: actual H.264 decode, bounded rendering, view resource controls and telemetry. These sockets never register or acquire motor-control authority.
- Lab `web/transmission.js`: controls/inspection and the TCP return edge to the actual C2 backend. Preview/inspection expansion preserves canvas state.

TCP **URV1** records use a 12-byte network-order prefix (`magic`, metadata length, payload length), followed by 66 bytes of fixed metadata and one unchanged H.264 Annex B access unit: **78 bytes of per-frame application overhead**, about 9.36 kb/s at 15 fps or 18.72 kb/s at 30 fps per stream. Fixed metadata includes camera ID, flags/clock scope, actual width/height, encoder UUID, access-unit sequence, relative PTS in microseconds, source sequence, source receipt timestamp, sender timestamp and requested-plan revision. Payloads are limited to 16 MiB before allocation/read. See `META` in `../../packages/video_protocol/urc_video_protocol/__init__.py` for field widths and byte order.

Browser **URB1** records preserve those H.264 bytes with bounded JSON metadata, adding the TCP connection epoch, codec string extracted from the SPS and receiver arrival time. Browser sockets have their own control/status messages and render feedback. The original C2 control WebSocket remains separate. The development launcher disables redundant WebSocket per-message compression for already-compressed video.

Keep native capture/encoder ownership outside ROS callbacks. The existing `EncodedAccessUnit` boundary and standalone metadata/wire adapters remain suitable places for later ROS 2 wrappers; no encoder/transmission DDS node was implemented or tested here.

## Validation and limits

Run local unit/API checks with `uv run pytest -q`; check `web/lab.js` and `web/transmission.js` with `node --check`. The original October 28 Mac check passed 71 lab tests, 31 C2 tests and 42 desktop tests. Current repository validation is recorded in `../../docs/VALIDATION.md`; the shared verification command checks both environments. These cover fragmented/invalid records, actual loopback TCP framing and epochs, byte/queue limits, shared pacing/priority, receiver restart cleanup, viewer resynchronization and separation from operator authority.

For explicit end-to-end verification, enable all five feeds in real C2 and start browser playback, then run:

```sh
uv run python verify_transmission.py
```

It uses the actual C2 receiver's browser render reports, not a generated playback stand-in. It verifies five simultaneous feeds and increasing rendered counters during a ten-second steady check, one combined payload budget, primary-only output at 1 Mb/s and 400 kb/s, zero-bandwidth stop/stale behavior, recovery, and both receiver- and sender-initiated reconnects. It restores the bench link inputs and leaves generators, encoding and transmission **OFF**, including on failure. Evidence: `artifacts/transmission-verification.json`. Browser screenshots and additional view pause/resume checks are saved alongside it. The observed test uses synthetic patterns; it does not establish useful terrain/manipulation quality or operational teleoperation performance.

The implemented sockets and destination validation intentionally accept loopback only. A later two-computer test must explicitly enable/configure a receiver LAN bind and sender destination, update the existing reverse-direction C2 priority/ACK addressing, and address clock mapping. The browser can remain on the C2 computer's localhost. No global firewall/network settings were changed. Real Wi-Fi/radio congestion, loss, long soaks, thermal/power behavior, physical capture, Sigma/QSV and two-host interoperability remain unverified.

Public technical references accessed October 28, 2026: [TCP byte-stream/retransmission semantics](https://www.rfc-editor.org/rfc/rfc9293.html#section-2.2), [Python asyncio stream flow control](https://docs.python.org/3.12/library/asyncio-stream.html), [WebCodecs](https://www.w3.org/TR/webcodecs/), [H.264 WebCodecs registration](https://www.w3.org/TR/webcodecs-avc-codec-registration/), and [WebSocket API](https://websockets.spec.whatwg.org/). AI-assisted local learning prototype requiring substantive human engineering validation and applicable course disclosure/approval before operational adoption or submission.
