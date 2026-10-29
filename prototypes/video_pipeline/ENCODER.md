# Local hardware encoder

October 28, 2026. User-authorized implementation in the original local lab; a curated copy is now in this prototype directory. The Mac now **actually hardware-encodes** the synthetic source buffers. The Encoding Decision core still only selects settings; the new Encoder owns media processing. Local loopback TCP transmission and actual C2/browser reception were subsequently implemented; see `TRANSMISSION.md`.

## Run and observe

Start the separate C2 Python backend (`:8870`) and this lab (`uv run python dev.py`, `:8872`). In the camera bank, enable video streams. In the Encoder node, enable encoding. The controls are independent and **both start OFF on every lab server start**. Enabling encoding alone never starts cameras. Disabling video streams first stops all encoder workers, then the generators; encoding intent may remain enabled and resumes when sources are explicitly enabled again. Disable encoding to stop just the compressed-video workload.

The node reports each actual native PID/session, requested output settings, accepted bitrate property, measured H.264 bitrate/FPS, output dimensions, frame count and submission-to-output p50/p95 delay. The format restart count is per camera. Inspect encoder state for queue/timestamp counters, failure details and recent lifecycle events.

**Show encoded previews** creates an on-demand decoder for each active stream. These 480×270/up-to-6-fps JPEG monitors come from the H.264 bytes, not from the source preview path. Hide them to stop the decoder/JPEG work; hiding the browser expires its five-second preview lease. The source bank's previews have a separate lease. Hiding previews does not stop enabled generators or encoding. Opening previews or an inspector preserves canvas pan/zoom and leaves all nodes visible. Isolation is an explicit toolbar checkbox; Focus node frames a selected node, and the canvas remains pannable/zoomable.

## Control and pixels

```text
Actual C2 priorities → shaped UDP → StatusManager → EncodingDecision plan
                                                     ↓ settings only
FFmpeg synthetic source → latest immutable NV12 → native encoder worker
                                                     ↓ H.264 access units
                                              bounded local OutputHub
                                                     ↓ optional only
                                           local decoder → JPEG monitor
```

`encoder_runtime.py` reconciles the latest plan at 5 Hz without requiring an open browser. It independently validates freshness, C2 eligibility, profile/native dimensions/FPS, bitrate bounds, requested combined budget, five-session maximum and the provisional 248,832,000 output-pixels/s Sigma cap. A stopped/stale planner or stale bandwidth produces no active sessions. Stale priorities retain the planner's existing eligible selection, consistent with the existing hold policy; omission/source loss/outage stop affected sessions. Allocation choices stay in `encoding_decision.py`.

Each selected camera has one persistent native GStreamer process. Python calls the source object's `latest()` directly; encoding does not fetch HTTP raw feeds, convert to RGB/JPEG, or route pixels through the browser. Frame sequence and local monotonic receipt time accompany the raw bytes. Intentional 30→15 fps selection skips source frames before copying them into the worker. Queues retain a few frames and discard older raw input when overloaded; they do not accumulate an unbounded frame backlog.

The current path **has copies**: immutable Python NV12 → OS pipe → allocated GstBuffer. Scaling uses CPU `videoscale`, then the hardware encoder accepts NV12. Hardware capture surfaces, GPU scaling and zero-copy are future optimizations requiring the actual capture platform; this lab does not claim them.

## Backends and changes

| Backend | Current implementation | Validation |
| --- | --- | --- |
| Mac | Hardware-only `vtenc_h264_hw`, requested CBR, realtime, frame reordering disabled, nominal one-second GOP | Actual H.264 output and decoded captures checked on this Apple Silicon Mac |
| Sigma/Linux | `qsvh264enc`, requested CBR, zero B frames, IDR interval zero, nominal one-second GOP | Adapter branch present; **not tested on Linux, Sigma, its drivers or an Intel GPU** |

There is no software-encoding fallback. Plugin probing only establishes factory availability; a stream becomes hardware-confirmed after actual encoded output from the hardware-only factory. A startup/output deadline or worker error closes that camera's session and invalidates its cached output. A failed settings/revision combination is not retried every reconciliation tick; a changed plan or explicit disable/re-enable can retry. Unexpected manager failures stop its workers.

A bitrate-only change updates the running encoder's property and retains its PID/session. The node separates **requested bitrate**, **accepted property readback** (integer kb/s rounding), and **measured byte rate**. Readback does not prove the new rate was met by a particular frame. Resolution/FPS changes close and recreate only that camera's worker; a new session UUID and IDR establish a new decoding epoch. Rapid plan changes are coalesced against the current revision before launching remaining workers. Stopping an output removes its latest/GOP cache and resets subscribers.

CBR is a rate-control request, **not an instantaneous traffic ceiling**. Short output windows can exceed the target, especially at keyframes/startup or after changes. The local Transmission module now adds compact headers, shared pacing, bounded freshness and keyframe recovery. Video uses its separate application byte shaper driven by the same bench link inputs. Actual radio congestion/loss and a production transport remain unvalidated.

## Local handoff for transmission

`encoded_output.py` provides an immutable `EncodedAccessUnit`, one complete Annex B H.264 access unit per record:

| Field | Meaning |
| --- | --- |
| `stream_id`, `encoder_session` | Camera ID and unique format/session epoch; reset decoder/reassembly when the epoch changes |
| `sequence` | Increasing encoded access-unit sequence within that epoch |
| `source_sequence`, `source_received_ns` | Matched synthetic source frame sequence and **local monotonic receipt time**, nullable if matching metadata was evicted; not a physical exposure time |
| `pts_ns` | Presentation time in nanoseconds relative to this encoder session's origin; compare deltas within the same session |
| `emitted_ns` | Local monotonic time when Python received the encoded access unit |
| `width`, `height`, `codec`, `stream_format` | Actual encoded dimensions; `h264`, `annexb` |
| `keyframe` | Actual IDR NAL detected in the Annex B payload; ordinary non-IDR intra frames are insufficient |
| `requested_plan_revision` | Revision associated with submitting the source frame; **not proof of per-frame bitrate application** |
| `data` | Immutable encoded bytes, including repeated SPS/PPS at IDRs via `h264parse config-interval=-1` |

No B frames are requested, so a separate decode-order timestamp is not exposed. Do not compare host monotonic clocks between machines; the transmission/receiver design will need an explicit clock mapping or relative-time policy.

A future in-process transmission adapter can use `runtime.hub.subscribe(stream_id, capacity=8)`, then drain the subscription. Capacities are limited to 1–64 access units. Subscribing requests a keyframe. A slow subscriber clears its queue on overflow and waits for an IDR; epoch changes and invalidation also reset it. It never stalls encoding, although downstream pacing/drop policy still needs to be designed. Call `close()` when done. Avoid adding an unbounded queue after this bounded handoff.

The hub also retains at most 64 frames / 8 MiB of one current, IDR-starting GOP per camera. If the bound is exceeded it waits for the next IDR. `GET /api/encoder/capture/cam-01` downloads that bounded diagnostic H.264 snippet; it is not a continuous streaming transport. `409` means no current decodable GOP. Active output is never replayed from the cache after omission/outage/stop. Preview decoder overload similarly waits for an IDR rather than resuming a broken prediction chain.

## Files, environment and checks

- `encoder_native.py`: build/probe and child-process environment. `native/encoder_worker.c`: GStreamer media/control worker and framed pipe protocol.
- `encoder_worker.py`: per-camera process ownership, raw submission, timestamp matching, accepted/observed metrics and clean shutdown.
- `encoder_runtime.py`: plan consumer, validation, reconciliation, preview leases and resource ownership.
- `encoded_output.py`: bounded local subscriber/GOP handoff. `web/encoder.js`: actual-output controls/monitoring.
- `app.py`: loopback same-origin controls, state, diagnostic captures and decoded previews.

Installed native ARM Homebrew GStreamer **1.28.8_1** for this implementation. It also installed/upgraded Homebrew dependencies, including FFmpeg **9.0.2_1** (previous 8.1.1 keg retained), GLib 2.90.1 and Homebrew Python 3.15.2. The lab's locked `.venv` remains Python 3.12; it does not depend on PyGObject or Homebrew Python. The older Intel `/usr/local` GStreamer remains in place. No global shell environment, camera drivers or OS network settings were changed. Required plugins are selected through lab-local symlinks and a lab-local registry, only in child environments. On Apple Silicon, `/opt/homebrew/opt/gstreamer` is explicit; `VIDEO_LAB_GST_PREFIX` can override it. Linux uses the local compiler/pkg-config/plugin installation and still requires validation with Intel drivers.

```sh
uv run python encoder_native.py   # build/probe only; no video generation
uv run pytest -q
node --check web/lab.js
node --check web/encoder.js
```

The full local suite passes 67 tests, including bounded output resynchronization, per-camera lifecycle/reconfiguration, freshness, invalid plans, API controls and cancellation during native process creation.

`verify_encoder.py` is an **explicit resource-using acceptance probe**. Temporarily enable all five feeds in the real C2 priority UI first. With the local services running, it enables synthetic sources/encoding, checks live bitrate changes without restarts, five distinct actual decoded previews, independently probes and decodes H.264 captures, samples a 20-second steady workload, checks primary-only emergency output, outage cache clearing, recovery and source-disable cleanup. It restores local link/video-share inputs and leaves sources/encoding OFF even after failure. It does not edit C2 priorities; restore your C2 draft/configuration afterward. Evidence is `artifacts/encoder-verification.json`, the five `encoded-cam-*.h264` captures and decoded JPGs.

The passing Mac check on October 28 used a 10 Mb/s link, 70→69% video share, the 20% headroom and five mixed 1080p30/360p30/360p15 outputs. During the 20-second sample, measured output was approximately 29.9–30.1 or 15.0 fps according to the selected profile. Maximum per-camera rolling p95 raw-submission→encoded-byte delay was below 30 ms in the final synthetic steady test (approximately 27.5 ms maximum across the rolling samples). Startup/reconfiguration are separate and can take longer. These values exclude physical capture, radio/network, receiver buffering/decoding/display and do not predict glass-to-glass latency. The 400 kb/s emergency check produced only Camera 01 at 320×180/15 fps; zero bandwidth cleared all workers and cached output. The recorded generator/native PIDs were confirmed gone after shutdown. A separate short high-allocation check produced three 1080p30 plus two 720p30 outputs (241,920,000 output pixels/s, below the cap), approximately 30 fps each. With only Camera 01 enabled, a separate 3840×2160/30 fps session was independently identified as H.264 with no B frames; measured FPS was approximately 30 and rolling p95 submission-to-output delay approximately 20 ms. See `artifacts/encoder-high-workload.json` and `artifacts/encoder-4k-verification.json`; these are short synthetic Mac checks, not sustained Sigma capacity benchmarks.

Synthetic patterns validate control/data plumbing, not terrain/manipulation image quality. Sigma session capacity, latency, resolution transitions, real-scene bitrate floors, long-run behavior, thermal/power performance and actual capture integration still need hardware measurements. The Sigma limits remain engineering planning estimates. ROS 2 metadata adapters and DDS were not implemented/tested for this module; see `ROS2_PORT.md`.

Public technical sources accessed October 28, 2026: [GStreamer hardware-only VideoToolbox H.264 encoder](https://gstreamer.freedesktop.org/documentation/applemedia/vtenc_h264_hw.html), [Intel QSV H.264 encoder and properties](https://gstreamer.freedesktop.org/documentation/qsv/qsvh264enc.html), and [H.264 parser](https://gstreamer.freedesktop.org/documentation/videoparsersbad/h264parse.html). Version-specific local probing and actual output tests support the Mac implementation; documentation is not Intel throughput evidence. AI-assisted local learning prototype, requiring substantive human engineering review/validation and applicable course disclosure/approval before a team submission or operational adoption.
