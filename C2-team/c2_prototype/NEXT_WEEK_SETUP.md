# Next-week chassis setup and acceptance test

The implemented path is:

```text
Xbox USB → C2 Python GUI → UDP through Wi-Fi router → Uno R4 WiFi
         → Matthew's left/right mixing → TB6612FNG drivers → four motors
Uno R4 → state acknowledgments / available encoder counts → router → C2
```

No onboard Linux computer is required for this bench milestone. Later, the onboard
computer will own the Arduino connection; the GUI's ROS adapter will replace this
direct UDP adapter. Do not run the original Xbox sender at the same time as C2.

## 1. Install the companion sketch

Matthew's [current repository](https://github.com/mafl8398/mini-rover-prototype)
uses UDP port 4210 and `throttle,steering` values. Its v6 sketch has no command-loss
watchdog or return acknowledgment. The new GUI deliberately requires the included
`c2-guard-v1` companion firmware; sending only the original string is insufficient.
The motor mixing and motor wiring are preserved. The network envelope adds a
session, sequence, enable/stop state and feedback; see [firmware/README.md](firmware/README.md).

1. Retain Matthew's existing sketch as a rollback copy. Open
   `firmware/mini_rover_c2/mini_rover_c2.ino` in Arduino IDE. Keep all sibling headers.
2. Install the **Arduino UNO R4 Boards** package. Select **Arduino UNO R4 WiFi**,
   not the classic Uno. Install Adafruit SH110X, NeoPixel and MPU6050 libraries,
   accepting their dependencies. This release compiled with R4 core 1.6.0.
3. Put the test router's SSID/password into `wifi_credentials.h` locally. Leave
   `C2_ENABLE_GPS` at 0 for the initial motor test. Do not commit Wi-Fi credentials.
4. With motor power isolated and the rover supported, upload to the correct R4 port.
   This development session has compiled the sketch but has NOT uploaded it.
5. Open Serial Monitor at 115200. Confirm `C2 GUARD V1`, Wi-Fi connection, the R4's
   IPv4 address and port 4210. Wi-Fi startup waits disabled if the router is missing.
   Close Serial Monitor before using that same USB port for another program.

## 2. Hardware and router checks

Use Matthew's existing motor power distribution, common logic ground and drivers.
Do not power motor windings from an Arduino GPIO or its 3.3 V regulator. Driver
voltage/current ratings and the actual motor load still need hardware confirmation.

| R4 signal | Existing function |
|---|---|
| D2 / D4 / D3 | Left direction 1 / direction 2 / PWM |
| D6 / D7 / D5 | Right direction 1 / direction 2 / PWM |
| D8 | Both drivers' STBY |
| D0 / D9 / D11 / D13 | Encoder inputs FL / RL / FR / RR |
| D12 | NeoPixel |
| A0 / D10 / D1 | OLED buttons A / B / C |
| A1 | Battery divider input |
| A2 / A3 | Sonar pins reserved in the default configuration |
| A4 / A5 | MPU6050 I2C; OLED uses Wire1/Qwiic |

Left front/rear driver channels are paired, as are right front/rear. There are two
independent drive commands, not four independent wheel controllers. Check wheel
polarity with the wheels raised. Keep STBY biased low during MCU reset using an
appropriate hardware pulldown if the carrier does not already provide one.

**Encoder finding:** the tested official R4 core has no external interrupt mapping
for D9 or D13. The companion sketch reports those channels as unavailable (`null`,
shown as N/A) instead of pretending the rear motors have measured zero speed.
Front interrupt counts still require a wiring/pulse test. Counts are unsigned;
there is no calibrated distance, signed speed or closed-loop control. Resolve the
rear encoder pin allocation together before depending on four-wheel odometry.

Join the PC and R4 to the same router/LAN, using a 2.4 GHz SSID compatible with the
R4. Avoid a guest network that isolates clients. Internet access is not required.
Use the board's displayed address; the router's own address is NOT the rover address.
A router DHCP reservation can keep it stable. Allow this Python app on the trusted
private test network if needed; do not turn off the firewall globally or expose
UDP 4210 to the Internet. The protocol is not authenticated or encrypted.

## 3. Check the GUI before applying motor power

1. Start C2 0.4. Verify Xbox stick values and the yellow arrow change while disarmed.
2. In **Connections & Live GPS**, enter the R4 IPv4 and **4210**, then **Connect rover**.
3. Expect **ROVER DISABLED**, an increasing acknowledgment number and recent age.
   Connect alone sends no enable. A timeout means check firmware/network/address;
   a UDP send succeeding does not prove receipt.
4. If STOP was latched by a previous session, use **Reset STOP**, wait for the
   returned disabled state, then return to **Drive & Arm**.
5. With neutral stick and LB released, click **Enable controls**. Expect returned
   **ROVER ENABLED** and zero applied throttle/steering.
6. Hold LB and make a small forward input. The preview shows requested drive and
   the returned state shows applied PWM. Release LB: drive must return to zero.
7. Test Disarm and Escape. Reset STOP must remain disabled. No unexpected output
   should appear when changing tabs, controller, focus or reconnecting.

The limit is 25% wheel PWM (up to 64/255), not 25% measured speed. A motor may not
start at that duty cycle under load. Check power, STBY, direction/PWM and mechanical
load before changing limits; increasing the limit is a deliberate firmware/UI change.

## 4. Raised-wheel powered test

Have a physical motor-power cutoff within reach. Power the drivers according to
Matthew's verified circuit, with wheels clear of the bench. Repeat neutral enable,
small forward/reverse and left/right commands, checking paired wheel directions.
Each test starts from disabled/neutral. Record observed result and stop timing.

| Test | Expected outcome |
|---|---|
| Release LB | Next command is zero; returned applied PWM becomes zero |
| Disarm or switch tab | MCU reports disabled; D8 low and PWM zero |
| Escape / STOP | Stop latched; Enable refused until Reset and a new Enable |
| Unplug Xbox | Local disarm; no automatic recovery after reconnect |
| Close app | Best-effort STOP plus receiver timeout if STOP is lost |
| Abruptly end the C2 process while driving | MCU stops from its own command timeout |
| Disconnect Wi-Fi / shut off test router | MCU stops; restored network must not resume motion |
| Stop return telemetry only (local test automation) | C2 faults and stops; no automatic re-enable |

The firmware requests a stop after 250 ms without valid ARM/DRIVE updates; PING,
GPS and invalid packets do not refresh that timer. It runs in the MCU loop, so a
blocking I2C/Wi-Fi call can increase real stopping time. Measure D8/PWM with the
scope during loss tests; do not claim a guaranteed 250 ms physical stop. Add an
independent watchdog/enable circuit and appropriate physical E-stop before broader
operation. A power cutoff may allow coasting; it is not a guaranteed mechanical brake.

After a connection fault, release the stick/LB, Disconnect, reconnect, Reset STOP
if needed, verify disabled feedback, then Enable deliberately. If the board has not
rejoined Wi-Fi, restart it with motor power isolated. Auto-reconnect is not implemented.

## 5. GPS and arm alongside the rover

The home Uno GPS bridge can connect by USB to the C2 laptop for a stationary test,
or to the future onboard computer without disturbing Matthew's pins. A rover-mounted
bridge needs an onboard process to forward telemetry; the current GUI's USB mode
only reads a port on the computer running the GUI. The R4's optional GPS relay is
implemented for a one-board wireless test after the explicit rewiring in
[GPS_HOME_TEST.md](GPS_HOME_TEST.md).

The arm requires its own Nucleo firmware and calibration. It cannot be driven by
Matthew's two-number chassis payload. [ARM_INTERFACE_PLAN.md](ARM_INTERFACE_PLAN.md)
describes the separate path. The GUI identifies the hardware but keeps arm output
as a preview until joint IDs, ranges and firmware handshake are agreed.
