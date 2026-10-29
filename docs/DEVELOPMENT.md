# Local development

Browser transition working draft, October 29, 2026. Human engineering review and applicable course AI disclosure/approval are required before using this as a team deliverable.

## Start

On this Mac, double-click **Open C2.command**. It installs the locked Python dependencies in `.venv`, then opens the local station. Keep its terminal running; Ctrl+C stops it and closes the mock/serial adapters.

From a terminal in this repository:

```sh
uv sync --frozen
uv run python scripts/dev.py --open
```

Default URL: <http://127.0.0.1:8870>. `--port 8871` selects another local port. The launcher reuses an existing C2 service on that port without killing unrelated processes. There is no auto connection, auto enable, or public listener. This is a local single-user application, without network authentication; do not expose it through a proxy or change the bind address.

Python 3.12 or 3.13 is required. `uv` manages the virtual environment; dependencies are pinned by `uv.lock`. No Node build is required. Node.js 18+ is used for verification only. The Python receiver relays local H.264 to native browser decoding; source generation and encoding stay in the separate private lab. The browser Gamepad API replaces the desktop pygame adapter for operator input.

## Folder map

| Folder | What to edit |
| --- | --- |
| `c2_web/` | Python service and headless adapters for existing functionality |
| `web/` | Browser UI, styles, interaction and rendering |
| `tests/` | Authority, timeout, API and snapshot tests |
| `scripts/` | Local launch tooling |
| `docs/` | Architecture, parity, development and validation notes |
| `c2_prototype/` | Preserved canonical desktop prototype; reusable model/UDP/GPS logic |
| `C2-team/` | Preserved upstream nested copy |
| `.venv/` | Ignored local dependencies |
| `data/` | Ignored temporary reference-comparison imports |
| `artifacts/` | Ignored local screenshots and test evidence |

## First bench session

1. Open Connections → Connect local mock. This creates only a loopback UDP receiver.
2. Return to Drive & arm. At neutral, release drive hold and click Enable controls.
3. Hold Space while pressing W/A/S/D, or drag the virtual stick while holding the drive button. Pointer release centers the stick. A mapped standard browser gamepad uses the selected left/right stick for throttle and steering, with LB/L1 hold. Raw mapping and rescan are available in Controller mapping.
4. Release hold to command zero. Esc latches STOP. Reset STOP leaves controls disabled.
5. Test Pause input and Drop ACKs from Connections. Page changes also disarm; to test timeout during active motion, use the Python integration tests. A stale-link fault requires disconnect/reconnect, then deliberate enable.
6. Bench arm preview inhibits chassis drive while jogging; no arm packets are transmitted. Disconnect an OC/ROS interface first because its upstream contract is chassis-only.
7. Drive → Start live video displays the five received H.264 feeds. Large view selects one feed without changing C2 priorities. Drive and Cameras reuse the same five views. The lab must independently enable sources, encoding and transmission. Original Generated demo/HTTP JPEG/PNG sources remain under Cameras → Prototype snapshot sources.
8. Position & GPS → Synthetic GPS → Apply source. Wait for multiple fixes to populate scatter. Export captures or load the included synthetic reference JSONL example.

Browser focus loss, tab hiding, navigation away, or operator WebSocket disconnect clears hold and disarms. A gamepad must be connected and the page focused. Only one tab owns controls; other tabs can view, disarm, or STOP. Release controls before acquiring them in another tab.

## Edit and test

The service has no auto-reloader by default. Stop/restart after Python changes; reload the page after browser changes. Every restart begins disarmed. No motor hardware is needed for these tests:

```sh
uv run --frozen python scripts/verify.py
# Without a display: append --skip-gui; omitted Tk checks are reported.
# A longer loopback soak: append --soak-seconds 60.
```

Tkinter is only needed for the legacy camera tests, not for the browser service. Automated tests use synthetic images and local mocks; they do not open physical cameras or receivers.

Keep commits focused on the `browser-ui-port` branch. Runtime buffers are in memory (up to 12,000 command rows, 20,000 GPS captures, 100 events). Exports are user-initiated downloads; restarting clears the buffers. GPS capture JSONL includes raw NMEA and receipt metadata; reference-comparison JSONL is a separate schema (see the example and original `GPS_COMPARISON.md`).

## Onboard and video-priority adapters

Connections provides OC loopback using the upstream Python supervisor/bridge with a local mock MCU. Claim onboard control, return to Drive, enable at neutral and verify returned state. ROS 2 uses the upstream OperatorNode when the ROS runtime and built interfaces are available in the selected Python environment; it is explicitly unavailable on this Mac. Save onboard run exports the returned capture fields. See PORT_PARITY.md for the interface boundaries.

The Cameras page owns the C2 video-priority list and enabled/omitted divider. Send priorities commits the draft to this backend, which publishes configuration at 2 Hz to a separate local receiver (default 127.0.0.1:8873). It is not a video encoder. See VIDEO_PRIORITIES.md for the wire contract and isolation of test traffic.

## Merge sequence

NET5 `971aec7` is already in this branch. After its merge, fetch the actual `main`
and `c2-net5-recovery` tips explicitly (this checkout originally tracked only main),
then merge `origin/main` into `browser-ui-port` and run the shared verification command.
A normal history-preserving upstream merge should require no backend re-port. Squash
or rebase merging NET5 may require resolving README/.gitignore ancestry conflicts.
Review any additional upstream commits before declaring parity. Keep desktop/firmware
and the pinned ROS adapters intact; do not silently copy NET5 changes into ROS vendor code.

The workflow in `.github/workflows/verify.yml` runs the same host checks on Ubuntu
24.04 with a virtual display. It does not run a real browser decoder, DDS, Arduino
compilation or devices. Test the physical browser/controller mapping separately.
Before making the browser the sole driving interface, check five-feed display plus
mock driving, focus loss, page changes, STOP/reset, input expiry, receiver loss and
reconnect. Primary-view selection must not change encoding priorities or motion state.
