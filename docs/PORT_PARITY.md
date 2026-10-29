# Backend → browser parity

October 29, 2026. Baseline: `c2-net5-recovery` commit `971aec79b103d9106dc47571f473b871fa9490cf`, merged into `browser-ui-port`. Upstream `main` remains `6ae96d1`. This covers the NET5 bench app and the separate ROS chassis dashboard, not field readiness.

| Backend capability | Browser implementation | Validation / limit |
| --- | --- | --- |
| Neutral enable, hold-to-drive, wheel cap, STOP/reset | Preserved Control policy; persistent safety controls | Browser/runtime and mock tests; no motors |
| Sliders and raw input vector while disarmed | Throttle/steering sliders, virtual stick/vector and keyboard | Browser controls; vector is input, not measured velocity |
| Left/right Xbox sticks, LB hold, raw mapping | Standard Gamepad API left/right selectors plus raw axes/button indices and rescan | Mapping checks pass; physical controller/browser mapping needs validation |
| Direct guarded UDP | Current NET5 RoverLink | Handshake, faults and no automatic restart tested |
| Browser Enable readiness | Fresh non-HELLO acknowledgment required before offering ARM | Avoids reproduced 150 ms delayed-initial-handshake timing failure; upstream timeouts unchanged, confirmation never auto-enables |
| Known-disabled idle degradation/recovery | Degraded status, Enable blocked pending fresh ACK; no automatic enable | Runtime regression test |
| Delayed ARM confirmation | NET5 PING progression; no movement before returned confirmation | 150 ms delayed mock enable and 10 s delayed soak passed |
| Packet rejection, timing and first-fault evidence | Live NET5 diagnostics, received MCU diagnostics, frozen first-fault display/export | Captured before STOP changes evidence; log retains it |
| Mock fault injection | ACK loss, command drop, 0–150 ms reply delay, input pause | Loopback only |
| Returned counts and unsigned pulse rates | FL/RL/FR/RR table with validity/staleness and N/A | No invented encoder data from mock |
| Arm preview, five joint jogs | Same preview policy; drive inhibited in bench arm mode | No arm transport; upstream onboard interface is chassis-only |
| GPS serial/rover/demo, validity/scatter | Headless adapter and preserved parser/statistics | Synthetic/parser tests; real USB GPS pending |
| GPS reference comparison and capture | JSONL import, metrics/plots and downloads | Same shared-origin/time interpolation; no inferred accuracy |
| Four generated/snapshot camera panes | Preserved HTTP JPEG/PNG and demo panes | Original panes preserved; later local receiver/player documented separately |
| Command pose/path and future OC request preview | Model path plus forward/turn preview with explicit not-sent marker | Toy geometry retained; not odometry |
| JSONL capture/export and readable diagnostics | UTC/monotonic input, feedback, faults and model records; scroll-preserving updates | Bounded buffers, intentional download |
| ROS dashboard claim/enable/disarm/STOP/reset | Browser OC controls and upstream Supervisor/ChassisBridge / OperatorNode adapters | Same host policy in OC loopback; real DDS unavailable on this Mac |
| ROS dashboard feedback loss / OC restart behavior | Local fault latch, no replay of cached motion, explicit claim/reset/enable | Core/host and adapter tests; DDS execution pending |
| ROS dashboard encoder validity and Save run | Full OC state table and 6000-row receipt-time capture export | Same upstream field contract, no calibrated wheel velocity |
| Local H.264 video receive/display | Shared Camera 01–05 panel in Drive/Cameras, selectable large Drive view, explicit start/stop and per-view pause | Loopback TCP and native browser playback tested separately; selection does not change priorities/motion |
| New C2 video-priority configuration | Draggable Camera 01–05 list plus enabled/omitted divider; Python owns revision/session/publication | Real C2-process UDP publisher to an independent local receiver; not a lab simulator |

The OC loopback adapter runs real upstream Python supervisor/bridge code with a localhost mock MCU and no DDS. Selecting ROS 2 instead uses the upstream OperatorNode and built urc_c2_interfaces in an available ROS environment. Missing ROS is explicit; the UI does not present loopback as DDS validation. The upstream ROS vendor adapters remain pinned to their documented baseline; they were not silently replaced with NET5.

Direct bench mode retains GPS/cameras/arm preview; the upstream ROS chassis contract has no arm/GPS/camera topics. The browser keeps those existing local panels and reports the interface boundary. Physical networking, stopping behavior, GPS, controllers, camera sources and Ubuntu/ROS runtime remain hardware/integration acceptance work. No actual motors or devices were operated.

Local extension authorized October 28, 2026: the C2 backend now also receives loopback TCP H.264 from the separate architecture lab and relays Camera 01–05 through dedicated browser video sockets. This preserves the parity baseline above and does not acquire motion authority. See `VIDEO_RECEIVER.md`; the receiver/player is committed locally for merge preparation, with no LAN exposure or GitHub push. The architecture lab remains outside this repository.
