# CU URC 2027 — C2 Command Station

Command-and-control software for the CU URC rover team. C2 provides the operator
interface for driving the chassis, requesting arm movement, and viewing rover
telemetry, GPS and camera imagery.

## Browser port development

The `browser-ui-port` branch includes the reviewed NET5/backend update and adds a local Python backend and browser UI alongside
the preserved desktop prototype. Start on a Mac with **Open C2.command**, or:

```sh
uv sync --frozen
uv run python scripts/dev.py --open
```

Open <http://127.0.0.1:8870>. It starts disconnected and disarmed. Use Connections
→ Connect local mock to exercise it without motors. The browser port includes
drive/gamepad input, guarded UDP, arm previews, GPS tools, telemetry/log exports,
four generated-demo/HTTP snapshot panes, NET5 diagnostics/recovery, OC loopback/optional ROS 2 controls, and C2-owned feed priorities. Python
3.12/3.13 and `uv` are required. Camera streaming/encoding design is outside this port.

See [development setup](docs/DEVELOPMENT.md), [architecture](docs/ARCHITECTURE.md),
[desktop parity and limits](docs/PORT_PARITY.md), and [validation](docs/VALIDATION.md).
This is an AI-assisted engineering prototype for human review and hardware
validation, not a field-ready system. The original desktop documentation follows.

The current release is **prototype 0.5 / NET5**, a Python desktop application for bench
testing. Development code is in [`c2_prototype/`](c2_prototype/).

## Current capabilities

| Capability | Status |
|---|---|
| Xbox controller input | Implemented; live stick indicators and input vector work while disarmed |
| Chassis command interface | Implemented over UDP for the included companion Uno R4 WiFi firmware; physical rover acceptance testing remains |
| Local rover test | Implemented; exchanges packets with a local simulated receiver without motor hardware |
| Enable, hold-to-drive, STOP and connection faults | Implemented; explicit enable and no automatic restart after a fault |
| GP-20U7 GPS | USB NMEA input, fix status, track, stationary scatter and log export implemented; physical sensor testing remains |
| Camera panels | Generated demos and HTTP JPEG/PNG snapshots; not low-latency driving video |
| Arm controls | Preview only; Nucleo firmware/transport and joint calibration are not implemented |
| ROS 2 / onboard-computer integration | Planned for Ubuntu 24.04 and ROS 2 Jazzy |

The app starts with chassis transport disconnected. The drawn rover and cyan
path are a command-driven mathematical model, **not measured rover position**.
RC input is currently emulated, not a physical receiver connection.

## Quick start

Use Python 3.10 or later with Tkinter. From the repository root, using the Python
environment you intend to run the app with:

```text
python -m pip install pygame Pillow pyserial
python c2_prototype/app.py --xbox
```

If `python` is not available in the terminal, select your installed interpreter in
VS Code or use its full executable path. The Windows launcher
`c2_prototype/launch.ps1` also supports `--xbox`.

1. Select **Xbox controller** and move the left stick. Check the sliders, input
   values and yellow arrow before enabling.
2. Center the stick, release **LB**, then click **Enable controls**.
3. Hold **LB** while moving the stick. Release LB to command zero motion.
4. **Disarm** disables controls. **STOP / Escape** latches a stop; **Reset STOP**
   clears the latch without enabling motion.
5. To exercise the network path without hardware, open **Connections & Live GPS**
   and select **Start local test**. Return to Drive & Arm and repeat the steps.

Without an Xbox controller, select **Sliders (demo)** and hold Space while adjusting
the sliders. Sliders can send commands if chassis transport is connected; always
check the connection banner. Changing tabs or application focus disarms controls.

## Prototype hardware and communication

```text
Xbox controller → C2 Python GUI → Wi-Fi router → Uno R4 WiFi
                → motor drivers → paired left/right chassis motors

Uno R4 → returned command state and available encoder counts → C2
```

The included companion firmware is based on Matthew's motor sketch. It preserves
the motor pin assignments and left/right mixing while adding acknowledgments,
command validation, explicit enable, STOP handling and a local command timeout.
**The original sketch cannot pass the new C2 handshake.** Follow the setup guide
before attempting a powered test; launching the GUI does not upload firmware.

The home GPS bridge targets an **ATmega328 Uno**, which is different from the
rover's **Uno R4 WiFi**. The optional R4 GPS relay requires physical pin changes.
Arm planning targets the **Nucleo-F446RE**, **DRV8825/NEMA 17 steppers**, and possible
**MG995 servos**. Arm commands are currently previews only.

## Documentation

- [Detailed app README](c2_prototype/README.md)
- [Operator walkthrough](c2_prototype/operator_guide.txt)
- [Chassis wiring, router setup and powered acceptance tests](c2_prototype/NEXT_WEEK_SETUP.md)
- [Firmware installation and command protocol](c2_prototype/firmware/README.md)
- [Home GPS test and rover GPS integration](c2_prototype/GPS_HOME_TEST.md)
- [GPS versus model/odometry comparison](c2_prototype/GPS_COMPARISON.md)
- [Arm hardware and proposed interface](c2_prototype/ARM_INTERFACE_PLAN.md)
- [ROS 2 and onboard-computer roadmap](c2_prototype/ROS2_INTERFACE_PLAN.md)
- [Verification results and limitations](c2_prototype/TEST_RESULTS.md)

## Verification

NET5 verification includes **42 unit/integration tests and 21 GUI checks**,
plus native C++ guard checks, a delayed-reply localhost soak test, and Uno R4 WiFi
compilation. The separate ROS workspace has 16 host-side tests; ROS runtime testing
is still pending. See [NET5 release notes](docs/NET5_RECOVERY.md).

Tests cover drive, release-to-zero, enable/disarm, STOP/reset, lost acknowledgments,
receiver timeout, rejection of stale commands, input-vector/model movement, GPS
parsing and the GUI controls. Run the Python suites from the repository root:

```text
python verify_all.py
# Optional: --cxx PATH_TO_G++ --arduino-cli PATH_TO_ARDUINO_CLI --arduino-config PATH_TO_CONFIG
```

These results do **not** establish physical motor stopping time, real router
performance, GPS accuracy or arm operation. The MCU command timeout is nominally
250 ms and is serviced by its loop; blocking peripheral calls can delay it. A GUI
STOP does not replace a physical emergency stop. Use the documented raised-wheel
acceptance tests before broader operation.

## Development direction

### This week's Ubuntu / ROS 2 migration

The current bench app is `c2_prototype/` (NET5). The historical
[0.4 archive](releases/c2-bench-v0.4.zip) predates the A2 encoder wiring fixes;
do not upload that archived firmware to the current circuit.
The new, separate [ROS 2 Jazzy workspace](ros2_ws/README.md) implements the C2
operator/dashboard and OC chassis bridge with a loopback mock, guarded R4 transport,
returned command state, encoder validity and capture export. Its host-side tests
pass; building and running it under actual Ubuntu/ROS remains pending.

- [This week's motor-test and encoder plan](docs/THIS_WEEK_PLAN.md)
- [Ubuntu on this Windows laptop: impact and setup](docs/UBUNTU_SETUP.md)
- [Engineering prompt and scope](docs/ENGINEERING_BRIEF.md)
- [Migration verification and remaining checks](docs/MIGRATION_VERIFICATION.md)

Ubuntu installation is currently paused. It is not needed to run the existing
Windows bench test. Future ROS work belongs in `ros2_ws/`, leaving the fallback intact.

The direct C2-to-Arduino connection is an interim prototype. The intended system
routes C2 operator requests through an onboard computer that validates commands
and owns the chassis and arm microcontroller connections. Each microcontroller
must continue enforcing its own limits and timeouts.

Next milestones include physical chassis/GPS validation, measured odometry,
arm protocol and homing, ROS 2 integration, concurrent low-latency driving video,
and synchronized mission logging.

## Contributing

Work in `c2_prototype/`, create a branch for changes, and include relevant test
results in the pull request. Keep Wi-Fi credentials, captured GPS logs, virtual
environments and generated build files out of commits. Firmware credential files
must retain placeholders when shared.

Local Wi-Fi settings now belong in ignored `c2_prototype/firmware/mini_rover_c2/wifi_credentials.local.h`. See the [NET5 setup and bench checklist](docs/NET5_RECOVERY.md).
