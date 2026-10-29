# 28 October: NET5 offline recovery verification

See [NET5 release notes](../docs/NET5_RECOVERY.md) for setup and physical checks.

- PASS: 42 Python unit/integration tests and 21 hidden-Tk GUI tests.
- PASS: 16 separate ROS workspace host tests; actual ROS/Ubuntu execution not tested.
- Native C++ guard tests now cover Wi-Fi session invalidation, rejection of old
  DRIVE packets and mandatory RESET/ARM after recovery.
- PASS: 30-second localhost drive with 80 ms delayed replies, release-to-zero, command loss,
  fail-closed recovery and fresh-session reconnect are exercised by soak_test.py.
- Uno R4 WiFi firmware compile: 93,044 bytes flash; 12,216 bytes RAM (GPS off).

The 150 ms delayed-ARM scenario failed before adding PINGs during enable wait
and passes afterward. A Windows UDP connection-reset exception also initially
terminated the mock after client disconnect; the mock now keeps serving new
sessions and an explicit reconnect regression covers it.

NET5 retains the original command send timestamps and watchdog limits. Idle
staleness blocks Enable without permanently faulting a known-disabled link.
Firmware reconnect and timing counters are compiled, not radio/hardware tested.
The pre-change NET4 working directory was preserved in a private local zip
outside this Git repository. Previous published revisions remain in Git history.

---

# 28 October: NET4 timing and readable diagnostics

Two captured faults have different evidence: one PC tick gap was 2,343 ms;
the other had a 47 ms PC tick gap but acknowledged-command age 359 ms,
with ARM already acknowledged and MCU enabled. Neither proves an encoder
fault. The cause of the long PC pause remains unconfirmed.

Changes:
- Chassis text area requests 10 lines instead of 5, reserves 210 pixels,
  and gets more available vertical space; motion previews request less height.
- Live text refresh preserves the top visible text index, fixing scroll resets.
- PC gaps of at least 350 ms are explicitly identified and latch a fault;
  stale buffered replies cannot authorize continued movement.
- Sample control/transport time after polling Xbox input, not before it.
- NET4 firmware caches the startup IP for display, queries WiFi status at most
  once per 100 ms, and refreshes OLED at 2 Hz instead of about 6.7 Hz.
  These reduce synchronous modem/display overhead; they are not proof of a
  hardware fix. IP display is the startup address; reset after network changes.
- 250 ms MCU command watchdog, 350 ms C2 acknowledgment limit, pin mapping,
  credentials and deliberate enable requirement remain unchanged.

Validation: 37 unit/integration tests and 21 hidden-Tk GUI checks passed,
including scroll-position preservation, PC freeze, dropped acknowledgments,
release to zero, STOP/reset and no automatic re-enable. Uno R4 WiFi compile
(core 1.6.0) passed: 92,144 bytes flash; 12,172 bytes RAM.
No physical rover operation or upload was performed. Timing improvements
require another hardware run; sustained I/O blocking can still trip a timeout.

Bench retry: restart canonical C2-team/c2_prototype/app.py; upload the matching
firmware/mini_rover_c2/mini_rover_c2.ino and verify C2-NET4-20261028 in USB serial.
Use its current nonzero IP and port 4210. With wheels clear, connect and observe
stable disabled telemetry for 10 seconds. Center sticks, leave LB released,
enable and wait for confirmation, then hold LB and apply a small input.
Release LB to check zero output; STOP must disable. If a fault occurs, save
Telemetry & Logs before reconnecting and retain the serial startup log.

---

# 28 October: NET3 startup readiness

Confirmed NET2 hardware log still printed 0.0.0.0 followed by Ready. NET3 waits
up to 30 seconds after WiFi.begin returns for connected status plus a usable unicast
IPv4, then checks UDP listener startup. Failure leaves outputs disabled, displays
an OLED/USB diagnostic and requires reset to retry. No command processing occurs
after failed startup. This does not establish why the address was unavailable or
fix a proven router fault; it prevents premature readiness and socket setup.
Credentials, motor mapping and motion timeouts were not changed.

Compiled successfully for UNO R4 WiFi core 1.6.0: 92,016 bytes flash and 12,140
bytes RAM. Not uploaded or hardware-tested by the assistant. NET2 test results
below remain historical; Python/control logic did not change in NET3.

---

# 28 October: NET2 bench communication update

Firmware startup marker: `C2-NET2-20261028`. A2 remains the encoder input;
sonar is inactive and D10 is the single display-page button.

A physical screenshot showed reply age 62 ms, acknowledged-command age 359 ms,
TX PING #17 versus ACK PING #13, PC update gap 62 ms and no rejected replies.
This establishes delayed acknowledgment progress, not a complete loss of replies.
The exact physical cause is not yet proven. NET2 reduces idle polling to 10 Hz
and coalesces bounded batches of routine PING/DRIVE replies. HELLO/ARM/STOP/
DISARM/RESET transitions still receive an immediate reply. Command watchdog and
feedback timeout limits are unchanged. Physical acceptance is still required.

Also fixed an error introduced in the prior A2 update: getIrqIndexFromPin queries
allocated IRQ state, so it must be called after attachInterrupt, not as a precheck.
The R4 core ignores unsupported IRQ pins. Front encoder pulses still need testing.

UNO R4 WiFi core 1.6.0 compilation passed: 91,368 bytes flash, 12,140 bytes RAM.
37 Python unit/integration tests and 20 hidden Tk tests passed; native C++ guard
tests passed. No firmware was uploaded by the assistant and no motor endpoint was
contacted by automated tests. Credentials were not edited. These changes apply to
the direct bench app; the separate ROS workspace still pins its original adapter.

---

# C2 0.4 verification — 24 October 2026

## 27 October: bench fault diagnostics

Added a first-fault snapshot with reply and acknowledged-command ages, TX/ACK
operation and sequence, enable wait, PC update gap, rejected-packet reason, and last
received MCU state. It appears in the connection/transport summaries and is included
in saved command records. Later STOP traffic cannot overwrite the first-fault snapshot.
Reconnecting starts a new snapshot. Removed the misleading claim that a no-reply
timeout identifies stock v6 firmware. Fault hints now replace pending-enable hints.
Firmware, protocol, command limits and timeout thresholds are unchanged.

Verified 36 unit/integration tests and 20 hidden Tk GUI tests. This does not diagnose
the physical rover yet; capture the next fault with motor power isolated. No firmware
was uploaded and no physical endpoint was contacted by these tests.

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
