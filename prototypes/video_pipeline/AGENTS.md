# Experimental video pipeline

Read `../../docs/VIDEO_SYSTEM.md`, README.md and the guide for the component you
are changing. For an encoder port, read HARDWARE_ADAPTERS.md before editing code.
This is a repository copy curated from a local learning lab on October 29, 2026.
Its original private workspace and evidence are not included or modified here.

## Boundaries

- This is a separately launched, loopback-only prototype. C2 does not depend on
  it being installed or running. Work here belongs in this directory; receiver
  integration belongs in `../../c2_web/`, browser playback in `../../web/`.
- StatusManager and EncodingDecision stay standard-library, metadata-only cores.
  C2 owns priorities/omissions; never add a simulator, editor or replacement C2
  heartbeat here. Stopped C2 inputs must become stale.
- Raw NV12 pixels bypass the decision core. EncoderRuntime owns worker lifecycle;
  the native worker owns media processing; Transmission owns pacing/socket queues.
  The browser and video sockets must never acquire or renew motor authority.
- `../../packages/video_protocol/` is the canonical wire contract. `video_wire.py`
  is only a compatibility import. Do not fork that implementation for a new encoder.

## Invariants and evidence

- Sources, encoding, transmission and previews default OFF. Enabling a downstream
  module must not implicitly start upstream generators. Tests may toggle synthetic
  workloads; turn them off and reap their PIDs afterward. Collapsed/hidden preview
  views must release conversion/decoding leases.
- Preserve Camera 01–05 names and source limits: one 4K30, four 1080p30. Provisional
  Sigma planning limits are five sessions and 248,832,000 output pixels/s, with
  adjustable video allocation and 20% encoder headroom. These are estimates.
- Require explicit hardware encoding. No silent software fallback, installed-driver
  changes, network exposure or physical camera/motor access as a routine test fix.
  Mac VideoToolbox was tested; Intel QSV is an unvalidated adapter branch.
- Preserve session/sequence identity, source receipt clock, normalized output PTS,
  IDR/SPS/PPS recovery, bounded raw/AU/viewer queues, deadlines and measured metrics.
  Requested settings, accepted properties and actual output are different evidence.
- Keep logs/captures/GStreamer registries/binaries in ignored `artifacts/`; no media,
  credentials, personal paths, private logs or generated environments in commits.
- Preview/inspector expansion preserves other nodes and pan/zoom. Isolation is explicit.
- Run `uv run --frozen pytest` and syntax checks for changed web files here, or the
  root `uv run --frozen python scripts/verify.py` for both apps. Unit tests need no
  FFmpeg/GPU. Native probes and end-to-end video tests are separate opt-in gates.
- ROS scaffolding is unbuilt/untested and belongs here until deliberately integrated.
  Do not claim mock/host/Mac results validate DDS, Sigma throughput or field quality.

For a port, report the OS/GPU/driver/GStreamer versions, factory and property mapping,
commands run, actual output, shutdown behavior and remaining gaps. Do not remove
failed gates, raise resource limits or edit expected measurements to make a test pass.
