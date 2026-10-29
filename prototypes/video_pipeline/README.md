# Experimental video pipeline and architecture lab

Curated into this repository on October 29, 2026 from a local learning prototype.
This directory contains runnable source, tests and guides. Captures, private logs,
compiled workers, GStreamer registries and the original workspace are not included.
It is a development harness with loopback transport, not an approved rover deployment.

Start with [the repository component map](../../docs/VIDEO_SYSTEM.md) and [hardware
adapter guide](HARDWARE_ADAPTERS.md). Coding agents must also read AGENTS.md.

## Run

Start C2 separately from the repository root:

```sh
uv sync --frozen
uv run python scripts/dev.py
```

In a second terminal, from this directory:

```sh
uv sync --frozen
uv run python dev.py --open
```

Open the [lab](http://127.0.0.1:8872/) and [C2](http://127.0.0.1:8870/#drive).
Only one producer can own ports 8872/8873 at a time. Enable all five feeds in C2
Cameras and send priorities. In the lab, enable **video streams → encoding →
transmission**, then **Start live video** in C2 Drive/Cameras. These are separate
resource controls and all start off. No motor connection or enable is needed.

C2 alone and the unit tests need no media stack. Actual source generation needs
FFmpeg on PATH. Actual encoding additionally needs a C compiler, pkg-config,
compatible GStreamer development libraries/plugins and a working hardware encoder.
Mac VideoToolbox was tested; the Intel QSV branch needs target-host validation.
The native media worker currently supports POSIX macOS/Linux, not native Windows.
See HARDWARE_ADAPTERS.md before installing/changing a driver stack.

## What the nodes represent

| Node/boundary | Source and guide |
| --- | --- |
| Virtual camera bank | `sources.py`: persistent testsrc2 raw NV12 buffers; no USB/OS camera emulation |
| External C2 observer | `status_runtime.py`: actual separate C2 PID/session/UDP publications |
| Simulated link | `simulated_link.py`: UDP metadata shaper; bandwidth/delay also feed video pacing |
| Status manager | `status_manager.py`, [STATUS_MANAGER.md](STATUS_MANAGER.md): pure input aggregation/freshness |
| Encoding Decision | `encoding_decision.py`, [ENCODING_DECISION.md](ENCODING_DECISION.md): requested profiles/budget only |
| Encoder | `encoder_runtime.py`, `encoder_worker.py`, `encoder_native.py`, `native/`; [ENCODER.md](ENCODER.md) |
| Encoded output | `encoded_output.py`: immutable AUs, timestamps/session/IDR, bounded subscriptions |
| Transmission | `transmission.py`, [TRANSMISSION.md](TRANSMISSION.md): real loopback TCP, shared pacing and reconnects |
| Shared wire format | [packages/video_protocol](../../packages/video_protocol/README.md); local `video_wire.py` only imports it |
| Optional ROS scaffold | `ros2/`, `ros2_status_adapter.py`, [ROS2_PORT.md](ROS2_PORT.md); not built or DDS-tested |

Source identities remain Camera 01 (3840×2160 at 30 fps) and Camera 02–05
(1920×1080 at 30 fps each), with distinct moving colored patterns. Full raw input
volume is 746.496 MB/s; that is local pixel volume, not a compressed/network bitrate.
The decision core retains provisional Sigma limits: five sessions, 248.832 MP/s of
output and maximum native dimensions/rate, with adjustable video share and 20% headroom.

The lab visualizes real processes. It never owns priorities, simulates C2 or creates
replacement C2 heartbeats. Raw frames bypass the decision policy. The C2 receiver
relays H.264 unchanged; the browser decodes it. Source/encoded JPEG monitors are
separate diagnostic workloads with short preview leases. Hiding previews saves only
preview work; explicitly disable transmission, encoding and generation to stop them.
Opening previews/inspectors preserves other nodes; isolation is an explicit checkbox.

## Tests and cleanup

```sh
uv run --frozen pytest -q          # hardware-free unit/API/policy/lifecycle tests
uv run python encoder_native.py  # explicit build/probe; no sources
uv run python verify_encoder.py  # explicit actual encoder acceptance
uv run python verify_transmission.py  # explicit actual C2/browser acceptance
```

The hardware acceptance scripts require the prerequisites in their guides. The TCP
acceptance run needs all five enabled in real C2 and browser playback active; it
checks budgets, outage/recovery and both reconnect paths. They leave workloads off
and write local ignored evidence to `artifacts/`. Source-only `verify.py` requires
explicitly enabled sources and does not stop them; disable them afterward.
The repository-wide `uv run --frozen python scripts/verify.py` also runs this
prototype's hardware-free tests in its own environment and checks its JavaScript.

Never commit local environments, captures, generated binaries, credentials or
registries. Historical figures in the detailed guides describe the original Mac
bench and do not validate a new machine. No Sigma throughput, radio loss, physical
camera timing/quality, two-host clock mapping or DDS validation is implied. Substantive
human engineering input/review and applicable course AI disclosure/approval remain
required before operational adoption or a team submission.
