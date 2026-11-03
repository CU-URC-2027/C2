# C2 repository: instructions for coding agents

Read README.md first, then the relevant component map/guide and the closest AGENTS.md.
The reviewed backend baseline is main / NET5 `971aec7` (October 29, 2026). Preserve
canonical `c2_prototype/`, the historical `C2-team/` copy and documented ROS vendor pins
unless the task explicitly changes those components. Do not silently port NET5 into ROS.

This experimental host branch deliberately changes the canonical Control/UDP/mock
boundary for confirmed disarm and negotiated PWM. Its matching Arduino changes are
isolated on `experimental/arduino-connection-pwm`; read docs/CONNECTION_RECOVERY.md.
Do not silently bring that sketch into this branch or update the pinned ROS adapters.

## Where changes belong

| Task | Location / first read |
| --- | --- |
| Browser station, receiver, controls | `c2_web/`, `web/`, `tests/`; docs/ARCHITECTURE.md and PORT_PARITY.md |
| Video testing or hardware encoder port | `prototypes/video_pipeline/`; docs/VIDEO_SYSTEM.md, its AGENTS.md and HARDWARE_ADAPTERS.md |
| Shared video framing | `packages/video_protocol/`; its README.md and AGENTS.md |
| Verification/CI | `scripts/verify.py`, `.github/workflows/verify.yml` |
| Existing chassis ROS code | `ros2_ws/`; its README and current interface/validation docs |

The video producer is deliberately a separately launched prototype, with its own
locked environment. C2 must start without that producer, FFmpeg, GStreamer or a GPU.
Both environments depend on the repository-local shared protocol package. Never fork
the wire implementation, copy a private working folder wholesale, or add captures,
credentials, local environments, absolute personal paths or compiled binaries.

## Invariants

- Start disconnected/disarmed. Reconnection, STOP reset, input-source change or input
  recovery never enables automatically. Preserve independent onboard/MCU watchdogs.
- Only a new increasing operator input sample renews motion freshness. Server ticks,
  pings, priority/video traffic, render reports and old samples must not renew it.
- Preserve one browser control owner, neutral/released-hold enable, page/focus/input
  expiry disarming, independent STOP and no replay of cached motion.
- Drive/Cameras share at most one video socket/decoder per camera per tab. Display
  selection never changes priorities or authority. Hidden views release resources.
- Keep loopback listeners/address validation by default. LAN/authentication changes,
  physical devices, firmware uploads and powered tests require deliberate task scope.
- Test with local mocks/synthetic media. Keep arm/RC/model/encoder-validity and measured
  vs requested states explicit. Host/Mac tests do not establish DDS or field readiness.
- File diagnostics default OFF and use an owner-selected existing backend folder.
  Keep file opening/serialization/writes off the control loop and settings requests
  nonblocking for WebSocket INPUT. Preserve bounded queues, visible loss/errors,
  exclusive file creation and normal-shutdown flush. Never commit diagnostic logs.
- Discovery is explicit/bounded/read-only and never renews ownership/input, clears
  STOP or enables. Verify selected identity in guarded feedback; do not auto-select
  a first response or take over a busy rover. Settings/profiles stay in ignored data/.
- Preserve shutdown's original sequence barrier/deadline across repeats/retries.
  PWM starts at 25%, respects advertised/legacy/ROS ceilings and uses mixed-wheel
  quantization bounds; increasing it while enabled disarms. No hardware validation
  or uploads are implied by host tests or a firmware build.

## Verify and report

Run `uv sync --frozen`, then `uv run --frozen python scripts/verify.py` at the root.
This covers both apps in their separate environments, JS checks, NET5/ROS host tests,
delayed loopback and available native guard checks. `--skip-gui` reports omitted Tk
checks. Actual encoder/browser/hardware tests are opt-in and have separate guides.
After media tests, disable workloads and confirm their worker PIDs exit.

Keep changes scoped and state tests run, failures, untested hardware/runtime and any
contract changes in the PR. Do not remove checks or weaken safety/resource limits to
obtain a pass. This is an AI-assisted prototype requiring substantive human engineering
review/validation and applicable course disclosure/approval before operational use.
