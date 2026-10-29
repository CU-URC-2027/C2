# Video components: start here

October 29, 2026. The browser station and the experimental video producer are in
one repository, with separate processes and Python environments. The producer is
a prototype, not the selected production rover implementation. The original local
learning workspace, captures, private logs and built binaries are not included.

## Component map

| Responsibility | Source | Change/test boundary |
| --- | --- | --- |
| Operator authority and drive input expiry | `c2_web/runtime.py`, `web/app.js` | Control samples only; video must never renew them |
| C2 priority configuration and publisher | `c2_web/priorities.py`, `web/priorities.mjs` | Camera order, omissions, revision/session; no pixels |
| C2 H.264 receive and fanout | `c2_web/video_receiver.py`, `api.py` | Passive TCP, bounded viewers, independent video sockets |
| Actual browser decode/display | `web/live-video.js`, `live-video.css` | Drive/Cameras share five views; explicit resource controls |
| Shared framing | [`packages/video_protocol/`](../packages/video_protocol/README.md) | One stdlib contract installed into both environments |
| Virtual camera bank | `prototypes/video_pipeline/sources.py` | Five raw NV12 sources; no USB camera drivers |
| Status inputs | `status_manager.py`, `status_runtime.py`, `simulated_link.py` inside the prototype | Actual C2 priorities and simulated estimator bandwidth |
| Encoding decisions | Prototype `encoding_decision.py`, `decision_runtime.py` | Standard-library metadata policy, requested profiles/budget |
| Encoder resource ownership | Prototype `encoder_runtime.py`, `encoder_worker.py` | Per-camera lifecycle, accepted/measured settings and timestamps |
| Hardware media implementation | Prototype `encoder_native.py`, `native/encoder_worker.c` | Build/probe, hardware properties, raw input and encoded output |
| Encoded handoff | Prototype `encoded_output.py` | Immutable access units and bounded IDR-aware subscriptions |
| Transmission | Prototype `transmission.py` | Shared pacing, per-camera TCP, deadlines/ACKs/reconnect |
| Process visualization | Prototype `app.py`, `web/` | Observe/control real processes; no replacement C2 simulator |

Paths in the prototype rows are relative to `prototypes/video_pipeline/`.
The two `video_wire.py` files are compatibility imports, not protocol copies.

```text
C2 priorities → local UDP shaper → StatusManager → EncodingDecision
                                                    ↓ settings
synthetic NV12 → hardware worker → EncodedAccessUnit → Transmission
                                                         ↓ TCP / URV1
browser ← WebCodecs / URB1 ← C2 Python receiver (no re-encode)
```

## Run the single-computer demonstration

Use Python 3.12/3.13 and `uv`; the checked-in Python preference is 3.12. Node.js
18+ is used only by verification. C2 alone needs no FFmpeg or GStreamer. Actual
prototype media additionally requires FFmpeg, a C compiler, pkg-config and compatible
GStreamer libraries/plugins. Read the [hardware guide](../prototypes/video_pipeline/HARDWARE_ADAPTERS.md)
before installing or changing a media stack.

Terminal 1, repository root:

```sh
uv sync --frozen
uv run python scripts/dev.py
```

Terminal 2, repository root:

```sh
cd prototypes/video_pipeline
uv sync --frozen
uv run python dev.py
```

Open C2 at <http://127.0.0.1:8870/#drive> and the lab at
<http://127.0.0.1:8872/>. In C2 Cameras, enable all five and send the priorities.
In the lab, enable **video streams → encoding → transmission**, independently.
In C2 Drive or Cameras, click **Start live video**. No motion connection/enable is
needed to watch video. Disabling playback only releases browser decoders; explicitly
disable transmission, encoding and source generation afterward to release the producer.

| Endpoint | Process | Purpose |
| --- | --- | --- |
| TCP/HTTP `127.0.0.1:8870` | C2 | Browser/control API and dedicated video WebSockets |
| TCP/HTTP `127.0.0.1:8872` | Prototype | Lab canvas, metadata and resource controls |
| UDP `127.0.0.1:8873` | Prototype | Actual C2 priority ingress and reverse ACKs |
| TCP `127.0.0.1:8874` | C2 | Passive encoded-video receiver, one connection per feed |

Start only one lab instance at a time; the original private lab uses these same ports.
The sender and video receiver deliberately validate loopback only. Two computers
require a separate deliberate LAN-bind/destination, reverse-priority and clock-domain
change; changing the sender text field alone is insufficient. No LAN deployment,
authentication or radio performance is established by this demonstration.

## Verification and evidence

From the repository root:

```sh
uv run --frozen python scripts/verify.py
```

This includes C2 tests, controller/video-view lifecycle checks, prototype unit/API
tests in its own locked environment, all browser/prototype JavaScript syntax,
NET5 desktop tests/GUI checks, ROS host checks, delayed loopback and available
native guard checks. It starts no synthetic camera or GPU encoder. `--skip-gui`
reports the omitted Tk checks. Firmware compilation is opt-in and never uploads.
The CI job uses the same hardware-free command; a green job does not validate codecs.

Explicit hardware/media checks, from the prototype directory:

```sh
uv run python encoder_native.py       # build/probe only; writes ignored artifacts
uv run python verify_encoder.py       # actual encoding; read ENCODER.md first
uv run python verify_transmission.py  # needs all five C2 feeds + browser playback
```

The end-to-end script checks increasing render counters, budget changes, outage,
recovery and receiver/sender reconnects. It restores bench inputs and turns producer
workloads off in its cleanup path. Keep browser playback off afterward as well.
Captures/metrics are local ignored evidence; never infer a new host's performance
from historical Mac measurements. See [validation](VALIDATION.md) for what was tested.

## Working with coding agents

Start with root `AGENTS.md`, then this map and the closest component's `AGENTS.md`.
Give an agent one component and acceptance goal, rather than asking it to rewrite
the whole pipeline. For example:

> Port the hardware worker for this GPU. Read the video prototype's AGENTS.md and
> HARDWARE_ADAPTERS.md. Keep the input/output contract, bounded queues and source
> clocks unchanged. Run the hardware-free suite first; then report the installed
> factory/properties, actual encoded output and cleanup evidence. Do not claim
> the Sigma capacity is measured or silently fall back to software encoding.

For protocol changes, update the shared package, both consumers and browser framing
together, with a version/compatibility decision. For a new camera, implement the
source boundary before changing policy or transmission. For an encoder, use the
[adapter guide](../prototypes/video_pipeline/HARDWARE_ADAPTERS.md); no C2 UI rewrite
should be required if it still emits the supported H.264 contract.

Maintain explicit statuses: **tested on a named host**, **implemented but unvalidated**,
or **proposed**. Preserve failures and limitations in the change description. A software
test does not approve field image quality, motor stopping or team interfaces. Promote
prototype modules into a stable rover package only after hardware and interface review;
do not make C2 automatically import/start this experimental producer.
