# Porting the Status manager to ROS 2

October 27, 2026. The Mac lab runs without ROS 2. The optional adapter and message package are source scaffolding, **not a compiled or tested ROS 2 integration**. Proposed topic names and QoS are not a team-approved interface baseline.

The standard-library `StatusManager` has no imports from FastAPI, FFmpeg, sockets, NumPy, or `rclpy`. The same `receive_priorities`, `receive_bandwidth`, and `snapshot` methods are used by both adapters:

| Current Mac adapter | ROS 2 adapter |
| --- | --- |
| Separate C2 backend → shaped UDP → rover receive callback → `FeedPriorities` | `/c2/video/priorities` subscription → same dataclass |
| Simulated local estimator → `BandwidthInput` | `/video/bandwidth_input` subscription → same dataclass |
| `GET /api/status-manager` → snapshot | `/video/status_inputs` publisher → typed snapshot |

`ros2/urc_video_interfaces/` contains typed definitions for `FeedPriorities`, `BandwidthInput`, and `StatusInputs`, plus an `ament_cmake` interface-package scaffold. `ros2_status_adapter.py` demonstrates the thin subscriptions/publisher around the unchanged core. Imports of ROS 2 occur only when that adapter's `main()` is run.

On the future ROS 2 host:

1. Review/finalize the contracts, package metadata (maintainer/license placeholders), topic names and stale-input threshold.
2. Copy `ros2/urc_video_interfaces` into a ROS 2 workspace's `src/`, build it with `colcon build --packages-select urc_video_interfaces`, and source the resulting install environment.
3. Run `ros2_status_adapter.py` using the host's ROS 2 Python environment with `status_manager.py` on its import path. Later package these two Python files in the team's `ament_python` node package.
4. Have C2's rover-side communication adapter publish `FeedPriorities`, and the link estimator publish `BandwidthInput`. The next video module subscribes to `StatusInputs`.
5. Validate publisher/subscriber QoS compatibility, reconnect/liveliness behavior, sequence/session resets and stale inputs on the real host/network before relying on them.

The reference adapter uses depth 1 with default reliable/volatile QoS as a minimal starting point. It republishes snapshots at 5 Hz so stale-state transitions remain observable when input callbacks stop. This is not a radio QoS recommendation. Decide durability/reliability/lifespan with the actual publishers and consumer; ROS 2 endpoints with incompatible QoS can fail to communicate. A bandwidth subscription and a retained priority configuration may need different profiles.

Receipt ages use local monotonic seconds; they do not assume synchronized clocks between C2 and the rover. JSON uses `null` for missing values. Typed ROS messages use presence flags plus zero/default values for absent counters/bandwidth, empty strings for absent sessions, and `-1.0` for missing ages. A zero bandwidth with `bandwidth_received=true` is a valid outage; it differs from no bandwidth input. Consumers must check presence and stale flags.

The adapter uses the single-threaded `rclpy.spin` path to preserve the core's single-owner model. A multithreaded executor requires a mutually exclusive callback group or a lock around core calls. The lab does not own C2 configuration or generate C2 priorities; a separate actual backend supplies them. The simulated UDP layer is a development harness and is not carried into the pure core. Final cross-machine C2 transport and authentication remain separate work.

Official ROS 2 Jazzy documentation source inspected October 27, 2026: [custom interfaces](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.rst), [Python publishers/subscribers](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.rst), [QoS compatibility and policies](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst). The rendered docs endpoint denied automated access, so its official repository source was used. No ROS 2 installation or system network reconfiguration occurred.

## Encoding Decision addition — October 28, 2026

The new `encoding_decision.py` is also standard-library only. A ROS wrapper can construct immutable `DecisionInputs` from StatusInputs and comms allocation metadata and publish the revisioned per-camera plan. Keep its source capability/availability input separate from raw image transport. The local 5 Hz runtime includes evaluation age and worker health; the local Encoder checks freshness and distinguishes requested from accepted/measured settings. The existing message scaffold does not yet define this plan or a decision ROS node. This metadata scaffold has no DDS validation; the separate local Encoder is documented below. See `ENCODING_DECISION.md`.

## Actual encoder boundary (October 28)

The local `encoder_runtime.py` now consumes the same plan metadata and owns native hardware worker lifecycles. `encoded_output.py` exposes immutable access units with stream/session ID, IDR flag, source receipt time and relative PTS, plus bounded subscriber queues. A ROS 2 node can wrap these ownership/metadata boundaries and replace the source `spec`/`latest()` adapter; keep heavy raw pixel copying, encoder ownership and bounded queues outside browser callbacks. Avoid assuming Python image messages provide zero-copy capture. No encoding-plan/output message definitions, encoder ROS node or DDS integration were built/tested here. Mac VideoToolbox works locally; Intel QSV on Sigma, camera surfaces and GPU scaling need platform validation. See `ENCODER.md` for exact fields, clock semantics, restart behavior and current limits.

The local Transmission module now consumes that bounded handoff through standalone wire adapters. It connects to a separately owned C2 TCP receiver and browser renderer; no ROS dependency is required. A future ROS wrapper should publish typed metadata/health and preserve encoder/session/keyframe identity, bounded queues and clock domains. The current local-only bindings and reverse priority path need explicit two-host configuration. No transmission DDS adapter was built or tested. See `TRANSMISSION.md`.
