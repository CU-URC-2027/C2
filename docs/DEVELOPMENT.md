# Local development

Browser-port working draft, October 27, 2026. Human engineering review and applicable course AI disclosure/approval are required before using this as a team deliverable.

## Start

On this Mac, double-click **Open C2.command**. It installs the locked Python dependencies in `.venv`, then opens the local station. Keep its terminal running; Ctrl+C stops it and closes the mock/serial adapters.

From a terminal in this repository:

```sh
uv sync --frozen
uv run python scripts/dev.py --open
```

Default URL: <http://127.0.0.1:8870>. `--port 8871` selects another local port. The launcher reuses an existing C2 service on that port without killing unrelated processes. There is no auto connection, auto enable, or public listener. This is a local single-user application, without network authentication; do not expose it through a proxy or change the bind address.

Python 3.12 or 3.13 is required. `uv` manages the virtual environment. Dependencies are pinned by `uv.lock`. No Node build is required. The scope is a browser port; no camera streaming or encoder architecture is included.

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
3. Hold Space while pressing W/A/S/D, or drag the virtual stick while holding the drive button. Pointer release centers the stick. A mapped standard browser gamepad uses left Y throttle, right X steering, LB/L1 drive hold.
4. Release hold to command zero. Esc latches STOP. Reset STOP leaves controls disabled.
5. Test Pause input and Drop ACKs from Connections. Page changes also disarm; to test timeout during active motion, use the Python integration tests. A stale-link fault requires disconnect/reconnect, then deliberate enable.
6. Disconnect chassis before enabling arm preview. Select a joint, enter arm preview, and hold jog. No arm packets are transmitted.
7. Cameras → Generated demo → Apply source. Alternatively enter an HTTP JPEG/PNG snapshot URL, matching the existing desktop prototype.
8. Position & GPS → Synthetic GPS → Apply source. Wait for multiple fixes to populate scatter. Export captures or load the included synthetic reference JSONL example.

Browser focus loss, tab hiding, navigation away, or operator WebSocket disconnect clears hold and disarms. A gamepad must be connected and the page focused. Only one tab owns controls; other tabs can view, disarm, or STOP. Release controls before acquiring them in another tab.

## Edit and test

The service has no auto-reloader by default. Stop/restart after Python changes; reload the page after browser changes. Every restart begins disarmed. No motor hardware is needed for these tests:

```sh
uv run pytest
uv run python -m unittest discover -s c2_prototype -p 'test_*.py'
node --check web/app.js
```

Tkinter is only needed for the legacy camera tests, not for the browser service. Automated tests use synthetic images and local mocks; they do not open physical cameras or receivers.

Keep commits focused on the `browser-ui-port` branch. Runtime buffers are in memory (up to 12,000 command rows, 20,000 GPS captures, 100 events). Exports are user-initiated downloads; restarting clears the buffers. GPS capture JSONL includes raw NMEA and receipt metadata; reference-comparison JSONL is a separate schema (see the example and original `GPS_COMPARISON.md`).
