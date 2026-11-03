# Local TCP video receiver

October 29, 2026. User-authorized local prototype. The C2 process passively listens on `127.0.0.1:8874` (override `C2_VIDEO_TCP_PORT`) and relays received Annex B H.264 to Camera 01–05 through dedicated binary WebSockets. Start playback explicitly in Drive or Cameras. Both workspaces share one panel and one socket/decoder per camera; selecting a large Drive view changes only layout. Hiding the tab, leaving both workspaces or stopping a view releases its decoder. Page changes still disarm motion. Existing priorities, control authority and snapshot/demo sources remain independent.

The shared `packages/video_protocol/` defines URV1 TCP records (12-byte prefix + 66-byte binary metadata + encoded frame) and URB1 browser messages (bounded JSON metadata + unchanged encoded bytes). `video_receiver.py` handles sequence/epoch validation, IDR/SPS/PPS startup, bounded viewer queues and acknowledgements. `api.py` adds `/api/live-video/state`, `/api/live-video/restart` and `/ws/video/{cam-01..cam-05}`. No receiver or video socket acquires motor authority; the original control WebSocket is separate. The development launcher disables redundant WebSocket compression.

Receiver-to-viewer queues are limited to six frames / 4 MiB; oversized frames are rejected. Slow viewers resynchronize at an IDR or disconnect. Restarting the listener closes active TCP sessions and clears queued output; the sender reconnects with a fresh connection epoch. Browser presentation uses an 80 ms PTS buffer bounded to five frames and scales its canvas backing image to the visible monitor while decoding the original received resolution. Received, decoded and rendered FPS are separate. Native codec support is checked; unsupported configurations show errors.

The default launcher validates loopback addresses only. The opt-in [two-VM ROS video
runner](ROS2_VIDEO_VM.md) now provides explicit private bind/peer allowlists and typed
metadata return traffic; it was exercised on Ubuntu/Jazzy VMs. Remote source ages
remain unknown, regardless of a remote sender's claimed clock scope. Local monotonic
source/receiver ages are valid only in same-host mode. These tests do not validate
Wi-Fi/radio, Sigma capacity, physical devices or independent-host clock mapping.

The shared verification command (`uv run python scripts/verify.py`) checks the receiver, control runtime, real five-feed synthetic TCP load with slow viewers and input expiry, and browser view lifecycle. See VALIDATION.md for current results. An actual synthetic five-stream browser test also checked shared bandwidth reductions, outage/recovery and both TCP reconnect paths; evidence remains private in the separate lab artifacts. The curated producer is in `prototypes/video_pipeline/`; see VIDEO_SYSTEM.md for testing and hardware adapters. Canonical/historical desktop sources were preserved.
