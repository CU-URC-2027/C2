# URC C2 prototype 0.4

A desktop command station with real Xbox input, an opt-in guarded UDP chassis
connection, live GP-20U7 GPS input, camera snapshots and motion previews.
It starts disconnected. The drawn rover remains a mathematical model even when
hardware is connected. Arm commands remain previews.

## Run

Close the older C2 window. From the URC folder in VS Code's PowerShell terminal:

```powershell
& 'C:\Users\Cutle\Anaconda\python.exe' '.\c2_prototype\app.py' --xbox
```

Alternatively run `launch.ps1 --xbox` from this folder. Use the same interpreter
in VS Code. No VM is needed for next week's GUI/Uno demonstration.
Python 3.10+ with Tk is required; optional inputs use pygame, Pillow and pyserial:

```powershell
& 'C:\Users\Cutle\Anaconda\python.exe' -m pip install pygame Pillow pyserial
```

These packages are already installed in this PC's Anaconda environment.
On Ubuntu the later ROS setup targets Ubuntu 24.04 / ROS 2 Jazzy; see the plan below.

## Start here

1. Select **Xbox controller**. Before enabling, move the left stick: the sliders,
   T/S values and yellow arrow respond. Select Right to use the other stick.
2. Center the stick and release LB. Click **Enable controls**, then hold **LB**
   while moving the stick. Wheel commands and the model path respond.
3. Release LB to zero the drive command. Disarm disables. Escape latches STOP;
   Reset STOP leaves controls disabled. Focus/tab/source changes disarm.
4. Without Xbox, use **Sliders (demo)** and hold Space while adjusting sliders.
   The input selector and hardware connection are separate: sliders CAN command
   the connected guarded chassis. RC (demo) is emulation and is blocked for live drive.
5. Open **Connections & Live GPS → Start local test** to exercise real UDP against
   a loopback mock, with no motors. Return to Drive, enable at neutral and drive.
6. For actual hardware, follow [NEXT_WEEK_SETUP.md](NEXT_WEEK_SETUP.md). The included
   companion firmware is required; the original sketch cannot pass the handshake.
7. For your ATmega328 Uno, follow [GPS_HOME_TEST.md](GPS_HOME_TEST.md). Select its USB
   port and 115200 baud in Connections & Live GPS. No serial port opens at startup.

## Added in 0.4

- Explicit rover address/port, handshake, returned enable/STOP state, applied PWM,
  acknowledgment age, encoder counts where available and connection faults.
- A companion Uno R4 sketch retaining Matthew's motor wiring/mixing, with strict
  command validation, 25% wheel cap, session/sequence ordering and a 250 ms local
  command watchdog. Stale traffic cannot silently restart motion after timeout.
- A loopback endpoint for checking the full UI → UDP → acknowledgment path.
- GP-20U7 NMEA input over a separate USB Uno bridge or an optional R4 UART relay.
  Checksum/fix checks, stale status, local East/North path, stationary scatter and
  raw/parsed GPS log export are implemented.
- Chassis command logs now include the last received rover state. Their freshness
  fields matter: a saved state is not necessarily a new measurement on every row.
- Concrete arm hardware/interface plan and home/rover GPS wiring plans.

## Guides

- [Next-week motor/router setup and acceptance test](NEXT_WEEK_SETUP.md)
- [Home GPS test and rover integration](GPS_HOME_TEST.md)
- [Nucleo / DRV8825 / MG995 interface plan](ARM_INTERFACE_PLAN.md)
- [Firmware and wire protocol](firmware/README.md)
- [Operator guide, also shown in Help](operator_guide.txt)
- [Ubuntu / ROS 2 / onboard-compute plan](ROS2_INTERFACE_PLAN.md)
- [Offline GPS-versus-reference comparison](GPS_COMPARISON.md)
- [Verification results and hardware limitations](TEST_RESULTS.md)

## Boundaries

The next-week adapter talks directly to the R4 over the router. The future ROS
adapter will send requests to the onboard computer, which owns the MCU links.
Neither ROS nodes nor arm firmware/transport are implemented here yet. Physical
RC input, battery telemetry and measured odometry remain future work.

Chassis wheel PWM is limited to 25%; no closed-loop speed control is implied.
The four motors are driven in paired left/right groups. Single-channel encoder
counts cannot establish signed motion. D9/D13 rear encoder inputs are unsupported
for attachInterrupt in the tested R4 core; the firmware reports null for them.

The path uses illustrative 1 m/s full-scale wheel speed and 0.5 m track width.
It is not measured position, even with a live connection. Live GPS logs are
separate from the synthetic/offline comparison; see GPS_HOME_TEST.md for how to
collect a meaningful comparison. GPS scatter is precision, not absolute accuracy.

Camera support is explicit HTTP JPEG/PNG snapshot polling and demo views. RTSP,
MJPEG, USB capture and concurrent driving video are not implemented. Tab switching
disarms, so this version is for bench tests, not video-only remote driving.

The MCU watchdog is serviced by its loop: blocking drivers can delay it. Its
actual stopping time still needs physical measurement. The GUI STOP is not a
physical emergency stop. No real hardware has been flashed or driven by these tests.

## Diagnostics and tests

From this folder, use the same Python interpreter:

```text
python controller_probe.py --seconds 15
python -m unittest discover -v
python gui_regression.py
```

The probe reads Xbox only. Tests use mock inputs, hidden Tk windows, local UDP and
HTTP endpoints; they do not connect to a physical rover. Native guard checks are
in `firmware/tests/guard_test.cpp` and compile with a C++11 compiler.

For an unmapped controller only, raw-index overrides remain available:
`python app.py --xbox --throttle-axis 3 --steering-axis 2 --hold-button 4`.
These indices are examples, not a universal Xbox mapping. Prefer SDL named controls.
