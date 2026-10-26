# C2 0.4 verification — 24 October 2026

Runtime: Windows, Anaconda Python 3.11.5, pygame 2.6.1 / SDL 2.28.4, Tk, Pillow,
pyserial. Tests connect only to local mock services; no motor/arm/GPS hardware was
operated or flashed. The new Arduino toolchains were installed under workspace
`tmp/`, not into the user's global Arduino installation.

## Automated results

**53 Python tests passed:** 34 unit/integration tests and 19 hidden-window Tk tests.
The C++ guard regression executable also passed.

- Chassis handshake does not arm; neutral enable, returned enable acknowledgment,
  bounded drive, release-to-zero, disarm, STOP/reset and close-to-stop.
- Real loopback UDP exchange, acknowledgment loss, client update freeze, receiver
  timeout and no restart from a delayed old-epoch DRIVE. Fault recovery never arms.
- Legacy/foreign/malformed commands cannot enable; invalid returned state rejected.
- Firmware C2Guard.h tested directly in native C++: parser bounds/embedded NUL,
  numeric overflow and malformed values, wheel cap, sequence ordering, ownership,
  epoch invalidation, STOP/reset, expiry before a late command and millis rollover.
- NMEA checksum, coordinate bounds, invalid/estimated fixes, freshness, duplicates,
  midnight transition, RMC speed and known stationary scatter fixture.
- GUI connection/local-test/disconnect buttons, arm inhibition with connected
  chassis, live GPS port/connect/disconnect/new-run/save controls, serial-error and
  stale/no-fix presentation using a mocked serial reader, GPS export.
- Existing Xbox mapped input, live arrow movement while disarmed, permitted model
  motion, LB/mouse/Space gates, reconnect and no automatic re-enable.
- Existing all drive/arm buttons, five tabs, source/stick dropdowns, camera buttons,
  snapshot transport/invalid data, synthetic/offline GPS, exports, focus regression
  and callback cleanup. No unexpected Tk callback errors were observed.

Commands from c2_prototype:

```text
C:\Users\Cutle\Anaconda\python.exe -m unittest discover -v
C:\Users\Cutle\Anaconda\python.exe gui_regression.py
```

Native test built with MinGW g++ / C++11 and warnings enabled:
`firmware/tests/guard_test.cpp`. Local networking and desktop tests required the
approved execution environment; the restricted environment blocked sockets/toolchain
launches. One loopback telemetry test initially addressed 0.0.0.0 instead of 127.0.0.1;
that fixture was corrected and the complete Python suite then passed.

## Arduino compilation

| Sketch/configuration | Target | Result |
|---|---|---|
| Home GPS USB bridge | arduino:avr:uno, core 1.8.8 | Compiled; 3,198 bytes flash / 305 bytes RAM |
| Chassis, GPS disabled | arduino:renesas_uno:unor4wifi, core 1.6.0 | Compiled |
| Chassis, GPS enabled in a test copy | Same R4 target/core | Compiled |

R4 libraries: Adafruit SH110X 2.1.15, NeoPixel 1.15.5, MPU6050 2.2.9 with GFX,
BusIO and Unified Sensor dependencies. The AVR bridge uses bundled SoftwareSerial.
Compilation verifies source/toolchain compatibility, not wiring, pulse timing,
UART levels, interrupt functionality or physical stopping time. GPS remains OFF
in the delivered default R4 configuration.

Core-source inspection found R4 D9/D13 lack external-interrupt mapping; the new
firmware checks interrupt registration and sends null for unsupported encoders.
A2 maps to IRQ7 for the optional front-left encoder remap. Physical pulse tests
are still required, including front channels.

## Visual inspection and controller history

Opened the actual 0.4 desktop window and inspected Drive & Arm and Connections &
Live GPS at 1220 × 900. The new controls and plot fit; the local-test button obtained
a disabled rover acknowledgment, and Disconnect returned to simulation. Hidden Tk
tests verify vector coordinates and model movement when inputs change.

The previous 0.3 session had a real Xbox One controller check: the operator confirmed
left-stick T/S and slider changes while disarmed; a live observation showed LB-held
nonzero wheel commands and model motion, then zero commands after LB release.
Those are previous-session observations, not a new physical controller test today.
This release regression-tested that adapter with emulated controller samples.

## Still requires hardware acceptance

No physical motor, arm, GP-20U7, camera or RC receiver input was tested today. No
real R4 Wi-Fi/router round-trip or firmware upload was performed. GPS USB transport
was tested with a mocked serial source, not a plugged-in sensor. The local mock
models the guard but does not execute Arduino peripherals; native tests exercise
the shared guard separately from GPIO/Wi-Fi code.

Run NEXT_WEEK_SETUP.md's raised-wheel tests and scope STBY/PWM timing. The command
watchdog is cooperative, so blocked peripheral calls can exceed its nominal 250 ms.
Use GPS_HOME_TEST.md for supply/wiring, raw NMEA, outdoor fixes, scatter and loss tests.
Arm commands remain previews pending the team's protocol, calibration and firmware.
Ubuntu/ROS/MoveIt, synchronized odometry/GPS fusion, rear encoder reassignment and
low-latency driving video remain planned work. Snapshot age is not video latency.
