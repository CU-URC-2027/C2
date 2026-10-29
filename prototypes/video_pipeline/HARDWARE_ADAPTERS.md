# Adapting the hardware encoder

October 29, 2026. Read AGENTS.md and `../../docs/VIDEO_SYSTEM.md` first. This guide
describes code boundaries and acceptance work, not a claim of universal GPU support.

## What works and what is a port

| Target | Current code | Evidence/status |
| --- | --- | --- |
| macOS / Apple VideoToolbox | `vtenc_h264_hw` | Actual synthetic H.264 encoding and C2 playback tested on Apple Silicon |
| Linux / Intel Quick Sync, including the intended Sigma | `qsvh264enc` branch | Implemented but not runtime-tested on Intel, Sigma or Linux; requires matching drivers/runtime/plugins |
| Linux VA-API | Possible `vah264enc` implementation | Requires an explicit new adapter and host validation; not selectable today |
| NVIDIA NVENC | Possible `nvh264enc` implementation | Requires an explicit new adapter and host validation; not selectable today |
| Native Windows media worker | POSIX pipe/control code is incompatible | Not supported; WSL/Linux GPU access also needs separate validation |

Factory availability, GPU generations and throughput are different facts. Inspect
the installed element and actual device/driver on the target; do not assume an Ubuntu
package includes the same plugin/version as this Mac. The provisional Sigma envelope
remains five sessions, max 4K30 per source and 248,832,000 output pixels/s. A faster
development machine must not silently raise those planning limits.

## Probe without starting video

From this directory:

```sh
uv sync --frozen
gst-inspect-1.0 --version
gst-inspect-1.0 vtenc_h264_hw   # Mac; use qsvh264enc for the Intel branch
uv run python encoder_native.py
```

The Python probe compiles the small native worker into ignored `artifacts/` and
reports factory availability. It does not start camera sources. On Apple Silicon it
uses `/opt/homebrew/opt/gstreamer`; `VIDEO_LAB_GST_PREFIX` overrides that prefix.
Linux uses pkg-config and the installed plugin/runtime setup. Environment overrides
and the GStreamer registry are child-local; no shell or global driver setting is changed.

The probe requires the encoding and existing preview-pipeline elements. If a plugin
is missing, report it and fix the environment deliberately. Do not install an entire
new GPU stack or replace hardware encoding with x264 as an automatic test repair.

## Smallest GStreamer port

1. Inspect `encoder_native.py`: build flags, platform/factory choice, required-element
   probe and child environment. Add a named, explicit backend rather than silently
   trying every installed encoder. Its helper must fail if hardware is unavailable.
2. Inspect `native/encoder_worker.c`: factory allowlist, launch description, RATE
   property handling, keyframe request, output and preview callbacks. Both the Python
   selection and native allowlist/pipeline must agree. Renaming a single factory is
   insufficient: properties, units, memory types and runtime mutability differ.
3. Map bitrate (the plan uses **bits/s**, current element properties use **kbit/s**),
   rate control, no B frames/reordering, lookahead, GOP/keyframe cadence and actual
   accepted values. Preserve prompt keyframe requests and IDR/SPS/PPS recovery.
   Do not report requested CBR as measured constant network throughput.
4. Preserve parsed output as H.264 Annex B, access-unit aligned, with parameter sets
   at IDRs. VideoToolbox's native output format is normalized by `h264parse`; keep
   that explicit. The browser decoder configuration comes from actual SPS metadata.
5. Keep the raw queue, encoded handoff, worker startup/output deadlines, pipe shutdown
   and process reaping bounded. Preserve GstSegment running-time normalization when
   hardware shifts PTS; do not match frames using wall clocks or a fixed frame delay.
6. Update probe expectations/acceptance scripts for the explicit backend, document
   its status and test it. An `nvh264enc`/`vah264enc` branch is not implemented merely
   because its name appears in this guide.

Optional decoded JPEG previews are diagnostics, separate from the C2 video path.
They may use a platform decoder or software decode and must stop when hidden.
The C2 Python receiver itself never decodes/re-encodes the video. Browser hardware
decode is a preference, with received/decoded/rendered FPS reported separately.

## Replacing the worker or capture stack

`EncoderRuntime(..., worker_factory=..., native_prepare=...)` is the existing
injection seam. The fake worker in `tests/test_encoder_runtime.py` demonstrates
lifecycle use; it is not a working hardware adapter. A replacement owns `start`,
`update`, `preview`, `command`, `state` and `close`, the current `settings`/startup
time/error fields, and truthful startup/output health. See the real `EncoderWorker`.
Keep live bitrate changes in the same session when supported; width/height/FPS
changes currently restart only the affected camera with a new encoder session.

The capture boundary is a source with `.spec`, `.running` and `.latest()`, returning
`(source_sequence, immutable_NV12_bytes_or_None, monotonic_receipt_seconds)`.
The current in-process pipe path copies raw bytes and scales on CPU. It does not
validate USB capture, DMA surfaces, camera exposure clocks or zero-copy integration.
A new capture adapter must make its timestamp and memory lifetime semantics explicit.

Output goes through immutable `encoded_output.EncodedAccessUnit` and `OutputHub`:
camera/session, AU/source sequences, source receipt clock, normalized nanosecond PTS,
emission time, actual dimensions, IDR flag, requested-plan revision and encoded bytes.
Transmitters consume this handoff; they must never read mutable raw capture buffers.
EncodingDecision consumes metadata only and should not change for a driver port.

## Acceptance gates and required report

- Run the root shared verification command. No GPU/FFmpeg is needed for this gate.
- Probe and record OS/CPU/GPU, driver/runtime, GStreamer version and selected factory.
  Verify actual hardware use with appropriate host tooling; a factory listing alone
  is not a sustained-capacity benchmark.
- Encode one finite synthetic stream and independently identify/decode its H.264,
  actual dimensions/FPS, parameter sets and frame reordering. Verify timestamps.
- Check live bitrate changes, per-camera format restart/IDR, missing frames, source
  stop, worker failure, preview lease release and cancellation during startup.
- Test all five within the provisional envelope; report requested/accepted/measured
  bitrates, output workload, delays, drops, thermals and test duration separately.
- Run `verify_encoder.py` and `verify_transmission.py` with real C2 playback. Exercise
  low bandwidth/outage/recovery, receiver/sender reconnect and independent viewer pause.
  Confirm every generator/native worker exits after disabling; leave workloads off.
- State what remains untested: real-scene quality, physical capture, long runs, radio
  loss, two hosts, clock mapping, DDS and the actual Sigma, as applicable. Synthetic
  patterns do not establish teleoperation visibility or an approved bitrate ladder.

No new hardware adapter is validated by unit mocks, a successful compile or copied
historical Mac figures. Include the commands and results in the change description;
keep large captures/registries/binaries local and ignored.

## Primary references

Official GStreamer documentation, accessed October 29, 2026: [VideoToolbox hardware-only
H.264](https://gstreamer.freedesktop.org/documentation/applemedia/vtenc_h264_hw.html),
[Intel QSV H.264](https://gstreamer.freedesktop.org/documentation/qsv/qsvh264enc.html),
[VA-API H.264](https://gstreamer.freedesktop.org/documentation/va/vah264enc.html),
[NVIDIA H.264](https://gstreamer.freedesktop.org/documentation/nvcodec/nvh264enc.html),
and [H.264 parser](https://gstreamer.freedesktop.org/documentation/videoparsersbad/h264parse.html).
Use the installed `gst-inspect-1.0` output for exact version-specific properties.
